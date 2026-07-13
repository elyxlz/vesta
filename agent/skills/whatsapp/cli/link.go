package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	vestadRequestTimeout = 10 * time.Second
	linkPollInterval     = 2 * time.Second
)

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
func registerVestadService(name string) (int, error) {
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
	body := fmt.Sprintf(`{"name":%q,"public":true}`, name)
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

func socketResultField(output []byte, field string) string {
	var result map[string]any
	if err := json.Unmarshal(output, &result); err != nil {
		return ""
	}
	if value, ok := result[field].(string); ok {
		return value
	}
	return ""
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

func runLink() {
	if phone, present := lookupFlag("phone"); present && phone != "" {
		runLinkPhone(phone)
		return
	}

	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}

	port := 0
	if flagPort, present := lookupFlag("port"); present {
		var err error
		port, err = parsePortFlag(flagPort)
		if err != nil {
			failJSON("%s", err.Error())
		}
	}
	if port == 0 {
		registeredPort, err := registerVestadService(linkServiceName())
		if err != nil {
			failJSON("%s", err.Error())
		}
		port = registeredPort
	}

	startArgs := []string{"--port", fmt.Sprintf("%d", port)}
	if hasBareFlag("acknowledge-ban-risk") {
		startArgs = append(startArgs, "--acknowledge-ban-risk")
	}
	output, exitCode, connected := trySocketCommand(getSocketPath(), "link-start", startArgs)
	if !connected || exitCode != 0 {
		fmt.Println(string(output))
		os.Exit(1)
	}

	pageURL := linkPageURL(os.Getenv("VESTAD_TUNNEL"), os.Getenv("AGENT_NAME"), linkServiceName(), port)
	printJSON(map[string]any{
		"status":       "linking",
		"url":          pageURL,
		"instructions": "Send the user this URL. On their phone: WhatsApp > Settings > Linked Devices > Link a Device, then scan the code on the page. The page keeps itself current; there is no rush.",
	})

	deadline := time.Now().Add(LinkSessionTimeout)
	for time.Now().Before(deadline) {
		time.Sleep(linkPollInterval)
		statusOutput, _, statusConnected := trySocketCommand(getSocketPath(), "link-status", nil)
		if !statusConnected {
			failJSON("daemon stopped answering during linking; check 'whatsapp daemon status'")
		}
		if socketResultField(statusOutput, "status") == string(AuthStatusAuthenticated) {
			printJSON(map[string]any{
				"status": "linked",
				"note":   fmt.Sprintf("History sync is settling: daemon stop/restart are locked for %s. Log lines like 'can't send presence' or a brief websocket EOF in this window are NORMAL. Do not restart anything.", SyncWindowDuration),
			})
			return
		}
	}
	trySocketCommand(getSocketPath(), "link-stop", nil)
	failJSON("no device linked within %s; link mode stopped. Retry with 'whatsapp link' when the user is ready (attempts are rate-limited)", LinkSessionTimeout)
}

func runLinkPhone(phone string) {
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}
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
