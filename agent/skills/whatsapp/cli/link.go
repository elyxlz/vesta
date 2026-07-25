package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const vestadRequestTimeout = 10 * time.Second

var (
	linkReadyTimeout = 30 * time.Second
	linkReadyPoll    = 200 * time.Millisecond
)

const linkNextStep = "Send the user this URL. Wait for them to scan it, then run `whatsapp status` once. Do not run connect again while this page is active."

func acquireConnectLock() (*os.File, error) {
	dir := stateDataDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create WhatsApp state directory: %w", err)
	}
	file, err := os.OpenFile(filepath.Join(dir, "connect.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, fmt.Errorf("open WhatsApp connect lock: %w", err)
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX); err != nil {
		file.Close()
		return nil, fmt.Errorf("lock WhatsApp connect flow: %w", err)
	}
	return file, nil
}

func releaseConnectLock(file *os.File) {
	syscall.Flock(int(file.Fd()), syscall.LOCK_UN)
	file.Close()
}

// linkServiceName is the vestad service (and tunnel path segment) for the link
// page: the shared "wa-link" for the default instance, suffixed per named
// instance so two instances' link pages never collide on one box.
func linkServiceName() string {
	if instance := extractInstance(); instance != "" {
		return "wa-link-" + instance
	}
	return "wa-link"
}

// linkPageURL builds the URL the user opens: the public tunnel route when the
// box has one, the raw local port otherwise (the caller then exposes it). The
// service segment matches the registered vestad service name.
func linkPageURL(tunnel, agentName, serviceName string, port int) string {
	if tunnel != "" && agentName != "" {
		return strings.TrimSuffix(tunnel, "/") + "/agents/" + agentName + "/" + serviceName + "/"
	}
	return fmt.Sprintf("http://localhost:%d/", port)
}

// registerVestadService registers a public service with vestad over the
// loopback (agent-token auth, self-signed TLS so verification is skipped, same
// trust model as the vestad skill's register-service curl -k) and returns the
// assigned port. Idempotent on vestad's side: same name, same port.
func registerVestadService(name string, requireBindable bool) (int, error) {
	vestadPort := os.Getenv("VESTAD_PORT")
	agentName := os.Getenv("AGENT_NAME")
	agentToken := os.Getenv("AGENT_TOKEN")
	if vestadPort == "" || agentName == "" || agentToken == "" {
		return 0, fmt.Errorf("VESTAD_PORT/AGENT_NAME/AGENT_TOKEN not set (not on a vesta box?); pass --port and expose it yourself")
	}
	client := &http.Client{
		Timeout:   vestadRequestTimeout,
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}},
	}
	url := fmt.Sprintf("https://localhost:%s/agents/%s/services", vestadPort, agentName)
	body := fmt.Sprintf(`{"name":%q,"public":true,"require_bindable":%t}`, name, requireBindable)
	req, err := http.NewRequest("POST", url, strings.NewReader(body))
	if err != nil {
		return 0, err
	}
	req.Header.Set("X-Agent-Token", agentToken)
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return 0, fmt.Errorf("vestad service registration failed: %v", err)
	}
	defer resp.Body.Close()
	var payload struct {
		Port int `json:"port"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil || payload.Port == 0 {
		return 0, fmt.Errorf("vestad service registration returned no port (HTTP %d)", resp.StatusCode)
	}
	return payload.Port, nil
}

func unregisterVestadService(name string, expectedPort int) error {
	vestadPort := os.Getenv("VESTAD_PORT")
	agentName := os.Getenv("AGENT_NAME")
	agentToken := os.Getenv("AGENT_TOKEN")
	if vestadPort == "" || agentName == "" || agentToken == "" {
		return nil
	}
	client := &http.Client{
		Timeout:   vestadRequestTimeout,
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}},
	}
	endpoint := fmt.Sprintf(
		"https://localhost:%s/agents/%s/services/%s/registrations/%d",
		vestadPort,
		agentName,
		name,
		expectedPort,
	)
	req, err := http.NewRequest(http.MethodDelete, endpoint, nil)
	if err != nil {
		return err
	}
	req.Header.Set("X-Agent-Token", agentToken)
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("vestad service unregistration failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("vestad service unregistration returned HTTP %d", resp.StatusCode)
	}
	return nil
}

// parsePortFlag parses a port flag value and returns an error if it is invalid.
func parsePortFlag(value string) (int, error) {
	if value == "" {
		return 0, nil
	}
	port, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("invalid --port value %q: %v", value, err)
	}
	if port < 0 || port > 65535 {
		return 0, fmt.Errorf("invalid --port value %q: out of range (0-65535)", value)
	}
	return port, nil
}

// linkServeArgs is the passthrough for a daemon this command cold-starts: it
// must land `whatsapp serve` on the same instance the link client polls
// (getSocketPath()/sessionName() are instance-scoped via extractInstance()),
// or a --instance link wedges polling a socket the default-instance daemon
// never opens.
func linkServeArgs() []string {
	if instance := extractInstance(); instance != "" {
		return []string{"--instance", instance}
	}
	return nil
}

// serveAndRunQRLink resolves the scan-page port (an explicit --port, else a
// vestad-registered public service), surfaces the scan URL to the user, then makes
// the one blocking socket call that serves the page and waits for the scan.
// socketCommand is the daemon verb that runs the link (self-hosted `link` or the
// user-owned `own-number-link`). Returns the daemon's terminal output + exit code.
func resolveQRLinkPage(requireBindable bool) (int, string, bool) {
	port := 0
	registered := false
	if flagPort, present := lookupFlag("port"); present {
		var err error
		port, err = parsePortFlag(flagPort)
		if err != nil {
			failJSON("%s", err.Error())
		}
	}
	if port == 0 {
		registeredPort, err := registerVestadService(linkServiceName(), requireBindable)
		if err != nil {
			failJSON("%s", err.Error())
		}
		port = registeredPort
		registered = true
	}
	pageURL := linkPageURL(os.Getenv("VESTAD_TUNNEL"), os.Getenv("AGENT_NAME"), linkServiceName(), port)
	return port, pageURL, registered
}

// serveAndRunQRLink keeps the synchronous QR flow used by own-number setup,
// which has more setup stages in the same invocation.
func serveAndRunQRLink(socketCommand string) ([]byte, int) {
	port, pageURL, registered := resolveQRLinkPage(true)
	printJSON(map[string]any{
		"status": "linking",
		"url":    pageURL,
		"next":   linkNextStep,
	})
	linkArgs := []string{"--port", fmt.Sprintf("%d", port)}
	if registered {
		linkArgs = append(linkArgs, "--unregister-service", linkServiceName())
	}
	if hasBareFlag("acknowledge-ban-risk") {
		linkArgs = append(linkArgs, "--acknowledge-ban-risk")
	}
	output, exitCode, connected := trySocketCommand(getSocketPath(), socketCommand, linkArgs)
	if !connected {
		failJSON("daemon stopped answering during linking; check 'whatsapp daemon status'")
	}
	return output, exitCode
}

type socketCommandResult struct {
	output    []byte
	exitCode  int
	connected bool
}

// startSocketCommand begins one daemon request and lets the caller stop waiting
// without cancelling the daemon-side command. The socket handler has already
// decoded the request before it enters the pairing body, so closing this client
// connection only discards the eventual response.
func startSocketCommand(sockPath, command string, args []string) (<-chan socketCommandResult, func(), bool) {
	conn, err := net.DialTimeout("unix", sockPath, SocketDialTimeout)
	if err != nil {
		return nil, func() {}, false
	}
	conn.SetDeadline(time.Now().Add(commandTimeout(command)))
	if err := json.NewEncoder(conn).Encode(SocketRequest{Command: command, Args: args}); err != nil {
		conn.Close()
		return nil, func() {}, false
	}
	result := make(chan socketCommandResult, 1)
	go func() {
		var resp SocketResponse
		if err := json.NewDecoder(conn).Decode(&resp); err != nil {
			result <- socketCommandResult{connected: false}
			return
		}
		if resp.Error != "" {
			data, _ := json.MarshalIndent(map[string]any{"error": resp.Error}, "", "  ")
			result <- socketCommandResult{output: data, exitCode: 1, connected: true}
			return
		}
		data, _ := json.MarshalIndent(resp.Result, "", "  ")
		result <- socketCommandResult{output: data, connected: true}
	}()
	return result, func() { conn.Close() }, true
}

// waitForQRReady waits only for the first live code, not for the user's scan.
// That keeps connect short enough for the agent to receive and relay the URL.
func waitForQRReady(port int, result <-chan socketCommandResult) (socketCommandResult, bool) {
	client := &http.Client{Timeout: time.Second}
	deadline := time.NewTimer(linkReadyTimeout)
	ticker := time.NewTicker(linkReadyPoll)
	defer deadline.Stop()
	defer ticker.Stop()
	qrURL := fmt.Sprintf("http://127.0.0.1:%d/qr.png", port)
	for {
		select {
		case terminal := <-result:
			return terminal, false
		case <-ticker.C:
			resp, err := client.Get(qrURL)
			if err == nil {
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					return socketCommandResult{}, true
				}
			}
		case <-deadline.C:
			data, _ := json.MarshalIndent(map[string]any{
				"error": "WhatsApp did not produce a QR code in time; run `whatsapp status` before retrying connect",
			}, "", "  ")
			return socketCommandResult{output: data, exitCode: 1, connected: true}, false
		}
	}
}

type activeQRLink struct {
	port    int
	service string
}

func currentQRLink() activeQRLink {
	output, _, connected := trySocketCommand(getSocketPath(), "daemon-status", nil)
	if !connected {
		return activeQRLink{}
	}
	var status struct {
		LinkPort    int    `json:"link_port"`
		LinkService string `json:"link_service"`
	}
	if json.Unmarshal(output, &status) != nil {
		return activeQRLink{}
	}
	return activeQRLink{port: status.LinkPort, service: status.LinkService}
}

func runLink() {
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}
	lock, err := acquireConnectLock()
	if err != nil {
		failJSON("%s", err.Error())
	}
	defer releaseConnectLock(lock)

	if active := currentQRLink(); active.port != 0 {
		pageURL := fmt.Sprintf("http://localhost:%d/", active.port)
		if active.service != "" {
			pageURL = linkPageURL(
				os.Getenv("VESTAD_TUNNEL"),
				os.Getenv("AGENT_NAME"),
				active.service,
				active.port,
			)
		}
		printJSON(map[string]any{
			"status": "linking",
			"url":    pageURL,
			"next":   linkNextStep,
		})
		return
	}

	port, pageURL, registered := resolveQRLinkPage(true)
	linkArgs := []string{"--port", fmt.Sprintf("%d", port)}
	if registered {
		linkArgs = append(linkArgs, "--unregister-service", linkServiceName())
	}
	if hasBareFlag("acknowledge-ban-risk") {
		linkArgs = append(linkArgs, "--acknowledge-ban-risk")
	}
	result, stopWaiting, connected := startSocketCommand(getSocketPath(), "link", linkArgs)
	if !connected {
		if registered {
			_ = unregisterVestadService(linkServiceName(), port)
		}
		failJSON("whatsapp daemon is not answering; run `whatsapp status`")
	}
	terminal, ready := waitForQRReady(port, result)
	stopWaiting()
	if !ready {
		if registered && !terminal.connected && currentQRLink().port == 0 {
			_ = unregisterVestadService(linkServiceName(), port)
		}
		fmt.Println(string(terminal.output))
		if terminal.exitCode == 0 {
			return
		}
		os.Exit(1)
	}
	printJSON(map[string]any{
		"status": "linking",
		"url":    pageURL,
		"next":   linkNextStep,
	})
}

func runLinkPhone(phone string) {
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}
	lock, err := acquireConnectLock()
	if err != nil {
		failJSON("%s", err.Error())
	}
	defer releaseConnectLock(lock)
	pairArgs := []string{"--phone", phone}
	if hasBareFlag("acknowledge-ban-risk") {
		pairArgs = append(pairArgs, "--acknowledge-ban-risk")
	}
	output, exitCode, connected := trySocketCommand(getSocketPath(), "pair-phone", pairArgs)
	if !connected {
		failJSON("daemon not running. Start with: whatsapp daemon start")
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}
