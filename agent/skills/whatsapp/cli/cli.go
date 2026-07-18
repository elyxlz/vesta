package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"runtime/debug"
	"strings"
	"syscall"
	"time"
)

// These parse os.Args directly rather than using flag.FlagSet because they are
// global flags that must be read before command dispatch (the per-command FlagSet
// only sees the remaining args after the subcommand).

// lookupFlag returns the value of --name (as "--name value" or "--name=value")
// and whether the flag was present, so callers can distinguish an absent flag
// from one set to the empty string.
func lookupFlag(name string) (string, bool) {
	flag := "--" + name
	prefix := flag + "="
	for i, arg := range os.Args {
		if arg == flag && i+1 < len(os.Args) {
			return os.Args[i+1], true
		}
		if strings.HasPrefix(arg, prefix) {
			return strings.TrimPrefix(arg, prefix), true
		}
	}
	return "", false
}

func extractFlag(name string) string {
	val, _ := lookupFlag(name)
	return val
}

func extractInstance() string         { return extractFlag("instance") }
func extractNotificationsDir() string { return extractFlag("notifications-dir") }

// hasBareFlag reports whether --name is present as a standalone flag.
func hasBareFlag(name string) bool {
	for _, arg := range os.Args {
		if arg == "--"+name {
			return true
		}
	}
	return false
}

func isNoNotifications() bool { return hasBareFlag("no-notifications") }
func isReadOnly() bool        { return hasBareFlag("read-only") }

func extractSkipSenders() map[string]bool {
	val := extractFlag("skip-senders")
	result := make(map[string]bool)
	if val != "" {
		for _, phone := range strings.Split(val, ",") {
			phone = strings.TrimSpace(phone)
			if phone != "" {
				result[phone] = true
			}
		}
	}
	return result
}

// stateDataDir is the per-instance data directory under ~/.whatsapp (the bare
// directory for the default instance, a named subdirectory otherwise).
func stateDataDir() string {
	base := filepath.Join(os.Getenv("HOME"), ".whatsapp")
	if instance := extractInstance(); instance != "" {
		return filepath.Join(base, instance)
	}
	return base
}

func getSocketPath() string {
	return filepath.Join(stateDataDir(), "whatsapp.sock")
}

func successResult(success bool, msg string) map[string]any {
	return map[string]any{"success": success, "message": msg}
}

func printJSON(v any) {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(data))
}

// failJSON prints an {"error": ...} object and exits nonzero, the single owner
// of the print-error-then-exit pattern the daemon and link commands share.
func failJSON(format string, args ...any) {
	printJSON(map[string]any{"error": fmt.Sprintf(format, args...)})
	os.Exit(1)
}

func writeDeathNotification(notifDir string, sig string) {
	notif := map[string]string{
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "daemon_died",
		"signal":    sig,
	}
	data, err := json.Marshal(notif)
	if err != nil {
		return
	}
	filename := fmt.Sprintf("%d-whatsapp-daemon_died.json", time.Now().UnixMicro())
	os.MkdirAll(notifDir, 0755)
	os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}

// liveAuthStatus maps a running daemon's daemon-status response to the
// authenticate verdict. The live connection is the truth: a fresh (re)link
// reports authenticated even when the on-disk auth-status.json still holds a
// stale logged_out that a later reconnect never cleared.
func liveAuthStatus(daemonStatus map[string]any, dataDir string) map[string]string {
	if loggedIn, ok := daemonStatus["logged_in"].(bool); ok && loggedIn {
		return map[string]string{"status": string(AuthStatusAuthenticated)}
	}
	// Daemon up but not logged in: surface its own auth_status (e.g. qr_ready).
	if authStatus, ok := daemonStatus["auth_status"].(string); ok && authStatus != "" {
		result := map[string]string{"status": authStatus}
		if authStatus == string(AuthStatusQRReady) {
			result["qr_image"] = "file://" + filepath.Join(dataDir, "qr-code.png")
		}
		return result
	}
	return map[string]string{"status": string(AuthStatusNotAuthenticated)}
}

// authStatusResult reports the live daemon's connection state when a daemon is
// answering on the socket, falling back to the cached auth-status.json only when
// no daemon is running (the cache can lag the real session across a reconnect).
func authStatusResult(sockPath, dataDir string) map[string]string {
	if output, exitCode, connected := trySocketCommand(sockPath, "daemon-status", nil); connected && exitCode == 0 {
		var live map[string]any
		if err := json.Unmarshal(output, &live); err == nil {
			return liveAuthStatus(live, dataDir)
		}
	}
	return authStatusMap(loadStateFromDisk(dataDir), dataDir)
}

func runAuthenticate() {
	dataDir := stateDataDir()
	resolved, err := resolveDir(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	printJSON(authStatusResult(getSocketPath(), resolved))
}

func runServe() {
	dataDir := stateDataDir()

	notifDir := extractNotificationsDir()
	noNotify := isNoNotifications()
	if notifDir == "" && !noNotify {
		notifDir = defaultNotificationsDir()
	}

	var err error
	dataDir, err = resolveDir(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// A stop-requested marker present at boot is stale: daemonStop only writes it
	// against a live daemon, so this fresh boot can't own it. Clearing it means a
	// marker leaked by a previous daemon (killed before it consumed it) can't
	// suppress THIS boot's genuine death notification.
	os.Remove(stopRequestedPath(dataDir))

	// Single-instance guard: take the exclusive device-store lock BEFORE opening
	// the whatsmeow store, so two daemons can never connect with the same device
	// identity (the device-session conflict). A held lock means another daemon is
	// already serving this store, so exit without connecting.
	lock, ok, err := acquireDaemonLock(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error acquiring daemon lock: %v\n", err)
		os.Exit(1)
	}
	if !ok {
		printJSON(map[string]string{"status": "already_running"})
		os.Exit(0)
	}
	serveDaemonLock = lock

	logger, logCloser := serveLogger(dataDir)
	if logCloser != nil {
		defer logCloser.Close()
	}

	// Device preservation: a preserve-reconnect set RestorePending before re-exec.
	// Restore the last-good device store BEFORE opening it (NewWhatsAppClient), so
	// SQLite cannot replay the removal that lives in the WAL.
	if loadStateFromDisk(dataDir).RestorePending {
		if err := restoreGoodDevice(dataDir, logger); err != nil {
			logger.Warnf("restore of last-good device failed: %v", err)
		}
	}

	if notifDir != "" {
		notifDir, err = resolveDir(notifDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
	}

	wac, err := NewWhatsAppClient(dataDir, notifDir, extractInstance(), isReadOnly(), noNotify, extractSkipSenders(), logger)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to initialize WhatsApp client: %v\n", err)
		os.Exit(1)
	}
	// The restore (if any) is done and the store is open; clear the flag so a
	// later ordinary boot does not restore a now-stale snapshot.
	wac.state.update(func(s *daemonState) { s.RestorePending = false })
	// Record this run's serve flags so `daemon restart` can bring the daemon back
	// faithfully (survives stops and crashes via the persisted state).
	wac.state.update(func(s *daemonState) {
		s.Args, s.PID, s.StartedAt = os.Args[1:], os.Getpid(), time.Now().UTC()
	})

	if err := wac.Connect(); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to connect: %v\n", err)
		os.Exit(1)
	}

	// Live voice calling wraps the connected client; it answers inbound calls from here on.
	wac.callMgr = NewCallManager(wac)

	sockPath := filepath.Join(dataDir, "whatsapp.sock")
	listener, err := startSocketServer(sockPath, wac)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: failed to start socket server: %v\n", err)
	}

	instance := extractInstance()
	if instance != "" {
		fmt.Fprintf(os.Stderr, "WhatsApp client initialized (instance: %s). Data: %s\n", instance, dataDir)
	} else {
		fmt.Fprintf(os.Stderr, "WhatsApp client initialized. Data: %s\n", dataDir)
	}
	if noNotify {
		fmt.Fprintln(os.Stderr, "Notifications: DISABLED (--no-notifications)")
	} else {
		fmt.Fprintf(os.Stderr, "Notifications: %s\n", notifDir)
	}
	if isReadOnly() {
		fmt.Fprintln(os.Stderr, "Running in READ-ONLY mode (no sending, no read receipts, no presence)")
	}

	if !wac.IsAuthenticated() {
		fmt.Fprintln(os.Stderr, "Not authenticated. Use 'whatsapp pair-phone --phone <number>' to authenticate.")
	}

	// Daemon came up without a device session (e.g. after a backup restore that
	// lost the whatsmeow session keys). Tell the agent once so it can prompt the
	// user to re-pair instead of silently failing every send. Runs once per
	// daemon boot, not per failed send.
	if wac.client.Store.ID == nil {
		fmt.Fprintln(os.Stderr, "Daemon started unpaired; notifying agent that re-pairing is required.")
		if err := WriteUnpairedNotification(notifDir, instance); err != nil {
			fmt.Fprintf(os.Stderr, "Warning: failed to write unpaired notification: %v\n", err)
		}
	}

	printJSON(map[string]string{"status": "serving"})

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	sig := <-sigChan

	fmt.Fprintf(os.Stderr, "Shutting down (signal: %v)...\n", sig)
	if _, err := os.Stat(stopRequestedPath(dataDir)); err == nil {
		os.Remove(stopRequestedPath(dataDir))
	} else {
		writeDeathNotification(notifDir, sig.String())
	}
	if listener != nil {
		stopSocketServer(listener, sockPath)
	}
	wac.Disconnect()
}

func stripGlobalFlags(args []string) []string {
	var filtered []string
	skip := false
	for _, arg := range args {
		if skip {
			skip = false
			continue
		}
		if arg == "--instance" || arg == "--notifications-dir" || arg == "--skip-senders" {
			skip = true
			continue
		}
		if strings.HasPrefix(arg, "--instance=") || strings.HasPrefix(arg, "--notifications-dir=") || arg == "--read-only" || arg == "--no-notifications" || strings.HasPrefix(arg, "--skip-senders=") {
			continue
		}
		filtered = append(filtered, arg)
	}
	return filtered
}

func runOneShot(command string) {
	sockPath := getSocketPath()
	// Self-bootstrap the background daemon (idempotent no-op when it is already
	// answering) so every agent command works cold, without the agent ever starting
	// anything by hand.
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("could not start the whatsapp daemon: %v; run `whatsapp status`", err)
	}
	output, exitCode, connected := trySocketCommand(sockPath, command, stripGlobalFlags(os.Args[1:]))
	if !connected {
		failJSON("whatsapp daemon is not answering; run `whatsapp status`")
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}

// parseFlags parses a command's flags, returning what the FlagSet wrote about the problem: the
// usage for `--help`, or the rejection plus the flag list for anything it does not accept. The
// FlagSet writes that text to an io.Writer and returns an error that on its own says nothing,
// so without capturing it the text lands on the daemon's stderr where nothing can read it.
func parseFlags(fs *flag.FlagSet, args []string) error {
	var written bytes.Buffer
	fs.SetOutput(&written)
	err := fs.Parse(args)
	if err == nil {
		return nil
	}
	text := strings.TrimSpace(written.String())
	if errors.Is(err, flag.ErrHelp) && !declaresFlags(fs) {
		// A FlagSet with nothing to list prints a bare "Usage of x:" header, which reads like the
		// answer went missing rather than like there is nothing to say.
		text = fs.Name() + " takes no flags"
	}
	if text == "" {
		return err
	}
	return errors.New(text)
}

func declaresFlags(fs *flag.FlagSet) bool {
	declared := false
	fs.VisitAll(func(*flag.Flag) { declared = true })
	return declared
}

// parseNoFlags gives a command that takes no flags a FlagSet anyway, so it reports that fact for
// `--help` and rejects a flag it does not know instead of ignoring its arguments and running.
func parseNoFlags(name string, args []string) error {
	return parseFlags(flag.NewFlagSet(name, flag.ContinueOnError), args)
}

// command describes one socket subcommand in a single place: its canonical name,
// short aliases, the leading positional args main rewrites into flags, whether it
// mutates state (blocked in read-only mode), an optional non-default socket
// deadline (for the long, blocking pairing commands), and its handler.
type command struct {
	name        string
	aliases     []string
	positionals []string
	// hidden keeps a command out of the usage list while it stays callable: the client-side
	// provision/link/daemon wrappers drive these over the socket, and the header already documents
	// them, so listing them again would only duplicate or invite a half-done call.
	hidden  bool
	write   bool
	timeout time.Duration // 0 = SocketTimeout; longer for blocking pairing commands
	run     func([]string, *WhatsAppClient) (any, error)
}

// commandTimeout is the socket deadline for a command: its own override, or the
// default SocketTimeout. Both the daemon (handleSocketConn) and the client
// (trySocketCommand) read it so a blocking `link` is not cut off mid-scan.
func commandTimeout(name string) time.Duration {
	if cmd, ok := lookupCommand(name); ok && cmd.timeout > 0 {
		return cmd.timeout
	}
	return SocketTimeout
}

var commands = []command{
	{name: "list-contacts", aliases: []string{"contacts", "search-contacts"}, run: cmdListContacts},
	{name: "add-contact", positionals: []string{"name", "phone"}, write: true, run: cmdAddContact},
	{name: "remove-contact", positionals: []string{"identifier"}, write: true, run: cmdRemoveContact},
	{name: "list-messages", aliases: []string{"messages"}, positionals: []string{"to"}, run: cmdListMessages},
	{name: "list-chats", aliases: []string{"chats"}, run: cmdListChats},
	{name: "send-message", aliases: []string{"send"}, positionals: []string{"to", "message"}, write: true, run: cmdSendMessage},
	{name: "send-file", aliases: []string{"file"}, positionals: []string{"to", "file-path"}, write: true, run: cmdSendFile},
	{name: "send-audio", write: true, run: cmdSendAudio},
	{name: "download-media", run: cmdDownloadMedia},
	{name: "send-reaction", aliases: []string{"react"}, positionals: []string{"to", "message-id", "emoji"}, write: true, run: cmdSendReaction},
	{name: "revoke-message", write: true, run: cmdRevokeMessage},
	{name: "create-group", write: true, run: cmdCreateGroup},
	{name: "leave-group", positionals: []string{"group"}, write: true, run: cmdLeaveGroup},
	{name: "list-groups", aliases: []string{"groups"}, run: cmdListGroups},
	{name: "update-group-participants", write: true, run: cmdUpdateGroupParticipants},
	{name: "backfill", positionals: []string{"to"}, run: cmdBackfill},
	{name: "rename-group", aliases: []string{"rename"}, positionals: []string{"group", "name"}, write: true, run: cmdRenameGroup},
	{name: "set-group-photo", write: true, run: cmdSetGroupPhoto},
	{name: "set-group-description", positionals: []string{"group", "description"}, write: true, run: cmdSetGroupDescription},
	{name: "set-profile-photo", positionals: []string{"file"}, write: true, run: cmdSetProfilePhoto},
	{name: "set-profile-name", positionals: []string{"name"}, write: true, run: cmdSetProfileName},
	{name: "get-group-invite-link", run: cmdGetGroupInviteLink},
	{name: "check-delivery", aliases: []string{"delivery"}, positionals: []string{"message-id"}, run: cmdCheckDelivery},
	{name: "pair-phone", run: cmdPairPhone},
	{name: "provision", hidden: true, timeout: ProvisionSocketTimeout, run: cmdProvisionManaged},
	{name: "list-received-contacts", run: cmdListReceivedContacts},
	{name: "archive-chat", positionals: []string{"to"}, write: true, run: cmdArchiveChat},
	{name: "archive-all-chats", write: true, run: cmdArchiveAllChats},
	{name: "delete-chat", positionals: []string{"to"}, write: true, run: cmdDeleteChat},
	{name: "clear-all-chats", write: true, run: cmdClearAllChats},
	{name: "call", positionals: []string{"to"}, write: true, run: cmdCall},
	{name: "say", positionals: []string{"text"}, write: true, run: cmdSay},
	{name: "hangup", write: true, run: cmdHangup},
	{name: "call-status", run: cmdCallStatus},
	{name: "daemon-status", hidden: true, run: cmdDaemonStatus},
	{name: "link", hidden: true, timeout: LinkSocketTimeout, run: cmdLink},
}

// cmdLink runs the whole self-hosted QR pairing synchronously in one socket call:
// serve the scan page on --port (when set), then block until the user scans or the
// window elapses, returning a terminal status. Single-flighted with every other
// pairing op, so a link during an in-flight provision is refused (never burns a
// rate-limit slot or serves a blank QR). Replaces the old link-start/status/stop
// trio and the client-side poll loop.
func cmdLink(args []string, wac *WhatsAppClient) (any, error) {
	var port int
	var acknowledged bool
	fs := flag.NewFlagSet("link", flag.ContinueOnError)
	fs.IntVar(&port, "port", 0, "Serve the QR link page on this port (0 = no page)")
	fs.BoolVar(&acknowledged, "acknowledge-ban-risk", false, "Override the pairing rate limit")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	// Gate on the linked FACT (Store.ID), not transient connection status.
	if wac.client.Store.ID != nil {
		return nil, fmt.Errorf("already linked; to pair a different account the user must first unlink this device from their phone (Linked Devices)")
	}
	release, ok := wac.beginPairing()
	if !ok {
		return nil, errPairingInProgress
	}
	defer release()
	if err := wac.state.tryRecordPairAttempt(time.Now(), acknowledged); err != nil {
		return nil, err
	}
	if _, err := wac.linker.linkQR(wac, port); err != nil {
		return nil, err
	}
	return map[string]any{"status": string(AuthStatusAuthenticated)}, nil
}

func cmdDaemonStatus(args []string, wac *WhatsAppClient) (any, error) {
	if err := parseNoFlags("daemon-status", args); err != nil {
		return nil, err
	}
	status := wac.GetAuthStatus()
	st := wac.state.snapshot()
	now := time.Now()
	result := map[string]any{
		"connected":                wac.client.IsConnected(),
		"logged_in":                wac.client.IsLoggedIn(),
		"auth_status":              string(status),
		"started_at":               st.StartedAt,
		"serve_args":               st.Args,
		"sync_window_seconds_left": int(syncWindowRemaining(st.LinkedAt, now).Seconds()),
		"pair_attempts_last_hour":  pairAttemptsInWindow(st.PairAttempts, now),
		"pair_attempts_last_day":   len(attemptsWithin(st.PairAttempts, now, PairDayWindow)),
		"pair_attempts_last_7d":    len(attemptsWithin(st.PairAttempts, now, PairWeekWindow)),
	}
	if wac.client.Store.ID != nil {
		result["number"] = "+" + wac.client.Store.ID.User
	}
	if build, ok := debug.ReadBuildInfo(); ok {
		for _, dep := range build.Deps {
			if dep.Path == "go.mau.fi/whatsmeow" {
				result["whatsmeow_version"] = dep.Version
			}
		}
	}
	return result, nil
}

// lookupCommand finds a command by its canonical name or one of its aliases.
func lookupCommand(name string) (command, bool) {
	for _, cmd := range commands {
		if cmd.name == name {
			return cmd, true
		}
		for _, alias := range cmd.aliases {
			if alias == name {
				return cmd, true
			}
		}
	}
	return command{}, false
}

func executeCommand(name string, args []string, wac *WhatsAppClient) (any, error) {
	cmd, ok := lookupCommand(name)
	if !ok {
		return nil, fmt.Errorf("unknown command: %s", name)
	}
	if wac.readOnly && cmd.write {
		return nil, fmt.Errorf("command %q blocked: instance is read-only", name)
	}
	return cmd.run(args, wac)
}

func cmdListContacts(args []string, wac *WhatsAppClient) (any, error) {
	var query string
	var limit int
	fs := flag.NewFlagSet("list-contacts", flag.ContinueOnError)
	fs.StringVar(&query, "query", "", "Optional search query")
	fs.IntVar(&limit, "limit", 50, "Max results")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	contacts, err := wac.store.SearchContacts(query, limit)
	if err != nil {
		return nil, err
	}
	return map[string]any{"contacts": contacts}, nil
}

func cmdAddContact(args []string, wac *WhatsAppClient) (any, error) {
	var name, phone string
	fs := flag.NewFlagSet("add-contact", flag.ContinueOnError)
	fs.StringVar(&name, "name", "", "Contact name")
	fs.StringVar(&phone, "phone", "", "Phone number (E.164)")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if name == "" || phone == "" {
		return nil, fmt.Errorf("--name and --phone are required")
	}
	contact, err := wac.AddContact(name, phone)
	if err != nil {
		return nil, err
	}
	return map[string]any{"contact": contact}, nil
}

func cmdRemoveContact(args []string, wac *WhatsAppClient) (any, error) {
	var identifier string
	fs := flag.NewFlagSet("remove-contact", flag.ContinueOnError)
	fs.StringVar(&identifier, "identifier", "", "Contact name or phone")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if identifier == "" {
		return nil, fmt.Errorf("--identifier is required")
	}
	if err := wac.store.DeleteManualContact(identifier); err != nil {
		return nil, err
	}
	return map[string]any{"success": true, "message": "Contact removed"}, nil
}

func cmdListMessages(args []string, wac *WhatsAppClient) (any, error) {
	var to, after, before, senderPhone, query string
	var limit, page int
	fs := flag.NewFlagSet("list-messages", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Chat filter (contact name, phone, or group)")
	fs.StringVar(&after, "after", "", "ISO-8601 datetime")
	fs.StringVar(&before, "before", "", "ISO-8601 datetime")
	fs.StringVar(&senderPhone, "sender-phone", "", "Filter by sender")
	fs.StringVar(&query, "query", "", "Search query")
	fs.IntVar(&limit, "limit", 50, "Max results")
	fs.IntVar(&page, "page", 0, "Page number")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}

	var afterTime, beforeTime *time.Time
	if after != "" {
		t, err := time.Parse(time.RFC3339, after)
		if err != nil {
			return nil, fmt.Errorf("invalid --after timestamp (expected RFC3339): %v", err)
		}
		afterTime = &t
	}
	if before != "" {
		t, err := time.Parse(time.RFC3339, before)
		if err != nil {
			return nil, fmt.Errorf("invalid --before timestamp (expected RFC3339): %v", err)
		}
		beforeTime = &t
	}

	var chatJID string
	if to != "" {
		jid, err := wac.ResolveRecipient(to)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve chat: %v", err)
		}
		chatJID = jid.String()
	}

	messages, err := wac.store.ListMessages(afterTime, beforeTime, senderPhone, chatJID, query, limit, page*limit)
	if err != nil {
		return nil, err
	}
	result := map[string]any{"messages": messages}
	if len(messages) == 0 && to != "" {
		result["note"] = "No messages found for this chat. If history exists on the phone, run 'backfill --to <contact>' to request it. If the contact is unknown, run 'add-contact' first."
	}
	return result, nil
}

func cmdListChats(args []string, wac *WhatsAppClient) (any, error) {
	var query, sortBy string
	var limit, page int
	var includeLastMessage bool
	fs := flag.NewFlagSet("list-chats", flag.ContinueOnError)
	fs.StringVar(&query, "query", "", "Search query")
	fs.IntVar(&limit, "limit", 50, "Max results")
	fs.IntVar(&page, "page", 0, "Page number")
	fs.BoolVar(&includeLastMessage, "include-last-message", false, "Include last message")
	fs.StringVar(&sortBy, "sort-by", "last_active", "Sort by (last_active or name)")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	chats, err := wac.store.ListChats(query, limit, page*limit, includeLastMessage, sortBy)
	if err != nil {
		return nil, err
	}
	return map[string]any{"chats": chats}, nil
}

func cmdSendMessage(args []string, wac *WhatsAppClient) (any, error) {
	var to, message, messageFile, replyTo string
	var longform bool
	fs := flag.NewFlagSet("send-message", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Recipient")
	fs.StringVar(&message, "message", "", "Message text (use '-' to read from stdin)")
	fs.StringVar(&messageFile, "message-file", "", "Path to a file containing the message body (use '-' for stdin). Preferred for multi-line text or content with apostrophes / quotes that complicate shell escaping.")
	fs.StringVar(&replyTo, "reply-to", "", "Message ID to reply/quote (optional)")
	fs.BoolVar(&longform, "longform", false, "Bypass the short-bubble lint for genuine reference material (a brief, a code block, a list they asked for).")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required")
	}
	if (message == "") == (messageFile == "") {
		return nil, fmt.Errorf("exactly one of --message or --message-file is required")
	}
	if messageFile != "" {
		body, err := readMessageSource(messageFile)
		if err != nil {
			return nil, fmt.Errorf("failed to read --message-file: %w", err)
		}
		message = body
	} else if message == "-" {
		body, err := readMessageSource("-")
		if err != nil {
			return nil, fmt.Errorf("failed to read stdin: %w", err)
		}
		message = body
	}
	if message == "" {
		return nil, fmt.Errorf("message body is empty")
	}
	if !longform {
		if reason := bubbleLintReason(message); reason != "" {
			return nil, fmt.Errorf("%s", reason)
		}
	}
	success, msg := wac.SendMessageWithPresence(to, message, replyTo)
	result := successResult(success, msg)
	if success && userAtIPPattern.MatchString(message) {
		result["delivery_warning"] = "Message contains a user@IP pattern which WhatsApp spam filters may silently drop. Use 'check-delivery' to verify delivery."
	}
	return result, nil
}

// readMessageSource loads a message body from a file path or "-" for stdin.
// Trailing newlines are stripped so content from `echo` or editor-saved files
// does not produce a leading/trailing blank line in the sent message.
func readMessageSource(src string) (string, error) {
	var data []byte
	var err error
	if src == "-" {
		data, err = io.ReadAll(os.Stdin)
	} else {
		data, err = os.ReadFile(src)
	}
	if err != nil {
		return "", err
	}
	return strings.TrimRight(string(data), "\r\n"), nil
}

func cmdSendFile(args []string, wac *WhatsAppClient) (any, error) {
	var to, filePath, caption, displayName string
	fs := flag.NewFlagSet("send-file", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Recipient")
	fs.StringVar(&filePath, "file-path", "", "Path to file")
	fs.StringVar(&caption, "caption", "", "Optional caption")
	fs.StringVar(&displayName, "display-name", "", "Override filename shown to recipient")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if to == "" || filePath == "" {
		return nil, fmt.Errorf("--to and --file-path are required")
	}
	success, msg := wac.SendFile(to, filePath, caption, displayName)
	return successResult(success, msg), nil
}

func cmdSendAudio(args []string, wac *WhatsAppClient) (any, error) {
	var to, filePath string
	fs := flag.NewFlagSet("send-audio", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Recipient")
	fs.StringVar(&filePath, "file-path", "", "Path to audio file")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if to == "" || filePath == "" {
		return nil, fmt.Errorf("--to and --file-path are required")
	}
	success, msg := wac.SendAudioMessage(to, filePath)
	return successResult(success, msg), nil
}

func cmdDownloadMedia(args []string, wac *WhatsAppClient) (any, error) {
	var messageID, to, downloadPath string
	fs := flag.NewFlagSet("download-media", flag.ContinueOnError)
	fs.StringVar(&messageID, "message-id", "", "Message ID")
	fs.StringVar(&to, "to", "", "Chat")
	fs.StringVar(&downloadPath, "download-path", "", "Save path")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if messageID == "" {
		return nil, fmt.Errorf("--message-id is required")
	}
	path, err := wac.DownloadMedia(messageID, to, downloadPath)
	if err != nil {
		return map[string]any{"success": false, "message": err.Error()}, nil
	}
	return map[string]any{"success": true, "file_path": path, "message": "Media downloaded"}, nil
}

func cmdSendReaction(args []string, wac *WhatsAppClient) (any, error) {
	var messageID, emoji, to string
	fs := flag.NewFlagSet("send-reaction", flag.ContinueOnError)
	fs.StringVar(&messageID, "message-id", "", "Message ID")
	fs.StringVar(&emoji, "emoji", "", "Emoji")
	fs.StringVar(&to, "to", "", "Chat")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if messageID == "" || emoji == "" || to == "" {
		return nil, fmt.Errorf("--message-id, --emoji, and --to are required")
	}
	success, msg := wac.SendReaction(messageID, emoji, to)
	return successResult(success, msg), nil
}

func cmdRevokeMessage(args []string, wac *WhatsAppClient) (any, error) {
	var messageID, to string
	fs := flag.NewFlagSet("revoke-message", flag.ContinueOnError)
	fs.StringVar(&messageID, "message-id", "", "Message ID to revoke")
	fs.StringVar(&to, "to", "", "Chat")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if messageID == "" || to == "" {
		return nil, fmt.Errorf("--message-id and --to are required")
	}
	success, msg := wac.RevokeMessage(messageID, to)
	return successResult(success, msg), nil
}

func cmdCreateGroup(args []string, wac *WhatsAppClient) (any, error) {
	var groupName string
	fs := flag.NewFlagSet("create-group", flag.ContinueOnError)
	fs.StringVar(&groupName, "name", "", "Group name")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	participants := fs.Args()
	if groupName == "" || len(participants) == 0 {
		return nil, fmt.Errorf("--name and participant phone numbers are required")
	}
	success, msg := wac.CreateGroup(groupName, participants)
	return map[string]any{"success": success, "group_name": groupName, "message": msg}, nil
}

func cmdLeaveGroup(args []string, wac *WhatsAppClient) (any, error) {
	var group string
	fs := flag.NewFlagSet("leave-group", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if group == "" {
		return nil, fmt.Errorf("--group is required")
	}
	success, msg := wac.LeaveGroup(group)
	return successResult(success, msg), nil
}

func cmdListGroups(args []string, wac *WhatsAppClient) (any, error) {
	var limit, page int
	fs := flag.NewFlagSet("list-groups", flag.ContinueOnError)
	fs.IntVar(&limit, "limit", 50, "Max results")
	fs.IntVar(&page, "page", 0, "Page number")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	groups, err := wac.store.ListGroups(limit, page*limit)
	if err != nil {
		return nil, err
	}
	return map[string]any{"groups": groups}, nil
}

func cmdUpdateGroupParticipants(args []string, wac *WhatsAppClient) (any, error) {
	var group, action string
	fs := flag.NewFlagSet("update-group-participants", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name")
	fs.StringVar(&action, "action", "", "add or remove")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	participants := fs.Args()
	if group == "" || action == "" || len(participants) == 0 {
		return nil, fmt.Errorf("--group, --action, and participant phone numbers are required")
	}
	success, msg := wac.UpdateGroupParticipants(group, action, participants)
	return successResult(success, msg), nil
}

func cmdBackfill(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	var count int
	fs := flag.NewFlagSet("backfill", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Chat to backfill")
	fs.IntVar(&count, "count", 50, "Number of messages")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required")
	}
	success, msg := wac.RequestBackfill(to, count)
	return successResult(success, msg), nil
}

func cmdRenameGroup(args []string, wac *WhatsAppClient) (any, error) {
	var group, name string
	fs := flag.NewFlagSet("rename-group", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name or JID")
	fs.StringVar(&name, "name", "", "New group name")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if group == "" || name == "" {
		return nil, fmt.Errorf("--group and --name are required")
	}
	success, msg := wac.RenameGroup(group, name)
	return successResult(success, msg), nil
}

func cmdSetGroupPhoto(args []string, wac *WhatsAppClient) (any, error) {
	var group, filePath string
	fs := flag.NewFlagSet("set-group-photo", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name or JID")
	fs.StringVar(&filePath, "file-path", "", "Path to image file")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if group == "" || filePath == "" {
		return nil, fmt.Errorf("--group and --file-path are required")
	}
	success, msg := wac.SetGroupPhoto(group, filePath)
	return successResult(success, msg), nil
}

func cmdSetGroupDescription(args []string, wac *WhatsAppClient) (any, error) {
	var group, description string
	fs := flag.NewFlagSet("set-group-description", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name or JID")
	fs.StringVar(&description, "description", "", "New group description")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if group == "" || description == "" {
		return nil, fmt.Errorf("--group and --description are required")
	}
	success, msg := wac.SetGroupDescription(group, description)
	return successResult(success, msg), nil
}

func cmdSetProfilePhoto(args []string, wac *WhatsAppClient) (any, error) {
	var filePath string
	fs := flag.NewFlagSet("set-profile-photo", flag.ContinueOnError)
	fs.StringVar(&filePath, "file", "", "Path to profile image (JPEG; PNG is converted to JPEG)")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if filePath == "" {
		return nil, fmt.Errorf("an image path is required (positional or --file)")
	}
	imageBytes, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read image file: %w", err)
	}
	if err := wac.SetProfilePhoto(imageBytes); err != nil {
		return nil, err
	}
	return map[string]any{"status": "updated"}, nil
}

func cmdSetProfileName(args []string, wac *WhatsAppClient) (any, error) {
	var name string
	fs := flag.NewFlagSet("set-profile-name", flag.ContinueOnError)
	fs.StringVar(&name, "name", "", "New display name (push name)")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if name == "" {
		return nil, fmt.Errorf("a name is required (positional or --name)")
	}
	if err := wac.SetProfileName(name); err != nil {
		return nil, err
	}
	return map[string]any{"status": "updated"}, nil
}

func cmdGetGroupInviteLink(args []string, wac *WhatsAppClient) (any, error) {
	var group string
	fs := flag.NewFlagSet("get-group-invite-link", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name or JID")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if group == "" {
		return nil, fmt.Errorf("--group is required")
	}
	success, link, msg := wac.GetGroupInviteLink(group)
	return map[string]any{"success": success, "link": link, "message": msg}, nil
}

func cmdCheckDelivery(args []string, wac *WhatsAppClient) (any, error) {
	var messageID, to string
	var limit int
	var recent bool
	fs := flag.NewFlagSet("check-delivery", flag.ContinueOnError)
	fs.StringVar(&messageID, "message-id", "", "Message ID to check")
	fs.StringVar(&to, "to", "", "Chat filter")
	fs.IntVar(&limit, "limit", 10, "Recent messages to show")
	fs.BoolVar(&recent, "recent", false, "Show recent outgoing statuses")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}

	var chatJID string
	if to != "" {
		jid, err := wac.ResolveRecipient(to)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve chat: %v", err)
		}
		chatJID = jid.String()
	}

	if recent || messageID == "" {
		results, err := wac.store.GetRecentOutgoingStatus(chatJID, limit)
		if err != nil {
			return nil, err
		}
		return map[string]any{"messages": results}, nil
	}

	status, ts, err := wac.store.GetDeliveryStatus(messageID, chatJID)
	if err != nil {
		return nil, fmt.Errorf("message not found: %v", err)
	}
	result := map[string]any{
		"message_id":      messageID,
		"delivery_status": status,
	}
	if ts != nil {
		result["delivery_timestamp"] = ts.Format(time.RFC3339)
	}
	return result, nil
}

// cmdProvisionManaged claims this account's one managed WhatsApp number and links
// the companion, synchronously: it blocks through the whole claim -> pair -> link
// handshake and returns the linked number or a terminal error. Idempotent on the
// linked FACT (Store.ID): an already-linked device returns its number without
// re-entering pairing, even in a not-yet-connected window. Single-flighted with
// every other pairing op. The top-level `whatsapp provision` (runProvision)
// cold-starts the daemon before dispatching this, so the agent runs one command
// and never orchestrates the steps itself.
func cmdProvisionManaged(args []string, wac *WhatsAppClient) (any, error) {
	if err := parseNoFlags("provision", args); err != nil {
		return nil, err
	}
	if wac.client.Store.ID != nil {
		// Already linked. If a takeover parked it, an explicit provision means
		// "reclaim the session": clear the park and reconnect (a plain send never
		// does this, so it can't ping-pong). If the other holder is still live it
		// simply re-parks. Otherwise it's already connected and this is a no-op.
		if wac.connModeIs(connParked) {
			wac.setConnMode(connNormal)
			if err := wac.EnsureConnected(); err != nil {
				return nil, fmt.Errorf("reconnect the parked session: %w", err)
			}
		}
		return map[string]any{"status": "linked", "msisdn": wac.state.snapshot().MSISDN}, nil
	}
	release, ok := wac.beginPairing()
	if !ok {
		return nil, errPairingInProgress
	}
	defer release()
	res, err := wac.linker.provision(wac)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"status": "linked",
		"msisdn": res.MSISDN,
		"note":   "Linked. Surface this number to the user with a wa.me link so they message you FIRST (reply-first, never cold-initiate).",
	}, nil
}

func cmdPairPhone(args []string, wac *WhatsAppClient) (any, error) {
	var phone string
	var acknowledged bool
	fs := flag.NewFlagSet("pair-phone", flag.ContinueOnError)
	fs.StringVar(&phone, "phone", "", "Phone number (E.164 format)")
	fs.BoolVar(&acknowledged, "acknowledge-ban-risk", false, "Override the pairing rate limit")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if phone == "" {
		return nil, fmt.Errorf("--phone is required (E.164 format, e.g. +393481234567)")
	}
	if wac.client.Store.ID != nil {
		return nil, fmt.Errorf("already linked; to pair a different account the user must first unlink this device from their phone (Linked Devices)")
	}
	release, ok := wac.beginPairing()
	if !ok {
		return nil, errPairingInProgress
	}
	defer release()
	// Check the ban guard first, but record the attempt only once a code is
	// actually generated: pairing fails cheaply when the websocket is not up yet
	// (fresh daemon still recompiling), and such a failure must not burn a slot.
	// The single-flight (beginPairing) means no concurrent caller can double-spend.
	now := time.Now()
	if err := checkPairAttempt(wac.state.snapshot().PairAttempts, now, acknowledged); err != nil {
		return nil, err
	}
	code, err := wac.linker.pairCode(wac, phone)
	if err != nil {
		return nil, fmt.Errorf("failed to generate pairing code: %v", err)
	}
	wac.state.recordPairAttempt(time.Now())
	return map[string]any{
		"pairing_code": code,
		"phone":        phone,
		"confirm":      fmt.Sprintf("Code generated for %s. CONFIRM this is exactly the number being linked: a typo'd number produces a code that silently never matches.", phone),
		"instructions": "Enter this code in WhatsApp > Linked Devices > Link a Device > Link with phone number",
	}, nil
}

func cmdListReceivedContacts(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	var limit int
	fs := flag.NewFlagSet("list-received-contacts", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Filter by chat")
	fs.IntVar(&limit, "limit", 50, "Max results")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	var chatJID string
	if to != "" {
		jid, err := wac.ResolveRecipient(to)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve chat: %v", err)
		}
		chatJID = jid.String()
	}
	messages, err := wac.store.ListMessages(nil, nil, "", chatJID, "[Contact:", limit, 0)
	if err != nil {
		return nil, err
	}
	return map[string]any{"contacts": messages}, nil
}

// cmdChatTarget runs a single-target chat command that accepts the target via
// --to or a leading positional (contact name, phone, group, or JID).
func cmdChatTarget(name, usage string, args []string, action func(string) (bool, string)) (any, error) {
	var to string
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.StringVar(&to, "to", "", usage)
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if to == "" && len(fs.Args()) > 0 {
		to = fs.Args()[0]
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required (contact name, phone number, group name, or JID)")
	}
	success, msg := action(to)
	return successResult(success, msg), nil
}

func cmdArchiveChat(args []string, wac *WhatsAppClient) (any, error) {
	return cmdChatTarget("archive-chat", "Chat to archive (contact name, phone, group, or JID)", args, wac.ArchiveChat)
}

func cmdArchiveAllChats(args []string, wac *WhatsAppClient) (any, error) {
	if err := parseNoFlags("archive-all-chats", args); err != nil {
		return nil, err
	}
	archived, errs, err := wac.ArchiveAllChats()
	if err != nil {
		return nil, err
	}
	result := map[string]any{"archived": archived}
	if len(errs) > 0 {
		result["errors"] = errs
	}
	return result, nil
}

func cmdDeleteChat(args []string, wac *WhatsAppClient) (any, error) {
	return cmdChatTarget("delete-chat", "Chat to delete", args, wac.DeleteChat)
}

func cmdClearAllChats(args []string, wac *WhatsAppClient) (any, error) {
	if err := parseNoFlags("clear-all-chats", args); err != nil {
		return nil, err
	}
	jids, err := wac.store.ListAllChatJIDs()
	if err != nil {
		return nil, fmt.Errorf("failed to list chats: %v", err)
	}
	var deleted, failed int
	var errs []string
	for _, jid := range jids {
		ok, msg := wac.DeleteChat(jid)
		if ok {
			deleted++
		} else {
			failed++
			errs = append(errs, fmt.Sprintf("%s: %s", jid, msg))
		}
	}
	result := map[string]any{
		"deleted": deleted,
		"failed":  failed,
		"total":   len(jids),
	}
	if len(errs) > 0 {
		result["errors"] = errs
	}
	return result, nil
}
