// Package main implements a WhatsApp CLI and daemon built on whatsmeow.
package main

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/jpeg"
	_ "image/png" // register PNG decoder so a PNG upload can be re-encoded to JPEG
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/appstate"
	waBinary "go.mau.fi/whatsmeow/binary"
	waCompanionReg "go.mau.fi/whatsmeow/proto/waCompanionReg"
	waStore "go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

type AuthStatus string

const (
	AuthStatusNotAuthenticated AuthStatus = "not_authenticated"
	AuthStatusQRReady          AuthStatus = "qr_ready"
	AuthStatusAuthenticated    AuthStatus = "authenticated"
)

// connMode is the daemon's connection posture, held in one atomic so every reconnect
// path honors it: the explicit state that makes the park and the pairing window safe
// against the background reconnect machinery.
type connMode int32

const (
	connNormal  connMode = iota // maintain a linked connection; recovery allowed
	connPairing                 // a foreground pairing owns the connection; recovery must leave it alone
	connParked                  // another device took over (yield); no path may reconnect until a re-link
)

type WhatsAppClient struct {
	client           *whatsmeow.Client
	store            *MessageStore
	logger           waLog.Logger
	dataDir          string
	notificationsDir string
	instance         string
	readOnly         bool
	noNotify         bool
	skipSenders      map[string]bool
	messageSenders   map[string]string
	senderOrder      []string
	sendersMutex     sync.RWMutex
	state            *stateStore
	linker           linker
	// managed is the pool-API client when this box links a managed number (nil on a
	// self-hosted QR box). It leases the residential proxy the cloud companion egresses
	// through and drives the user-owned (BYO) number flow.
	managed       *managedAuth
	proxyMu       sync.Mutex
	proxyURL      string // cached residential proxy lease for the process lifetime
	egressCache   map[string]egressInfo
	authStatus    AuthStatus
	authMutex     sync.RWMutex
	qrPath        string
	currentQRCode string // guarded by authMutex, cleared on success
	// pairMu single-flights every pairing op (provision, QR link, phone code): only
	// one runs at a time, so a failed one leaves a clean client for the next and no
	// two pairings ever race for the rate-limit slot or the QR channel.
	pairMu sync.Mutex
	// mode is a connMode; every reconnect path reads it so park and pairing are
	// respected. Atomic so the event dispatcher reads it without a lock.
	mode              atomic.Int32
	linkMu            sync.Mutex // guards linkServer
	linkServer        *http.Server
	presenceActive    bool
	presenceMutex     sync.RWMutex
	lastMessageSentAt time.Time
	connectMutex      sync.Mutex
	connRecoverOnce   sync.Once
	staleMu           sync.Mutex // guards staleDetectorDone
	staleDetectorDone chan struct{}
	transcribeSem     chan struct{} // limits concurrent audio transcriptions
	readQueueMu       sync.Mutex
	readQueue         map[string]*chatReadBatch // keyed by chatJID|senderJID; coalesces read receipts in order
	callMgr           *CallManager              // live voice calling; set in serve after Connect, nil for one-shot clients
	// Data-plane offload (see enqueueWork): message/receipt handling runs on one
	// FIFO worker so a slow store write never stalls whatsmeow's serial node loop.
	msgWork    chan func()
	workerDone chan struct{}
	// Device preservation (see preserve.go): the good-device snapshot throttle and
	// the connection-stability timer that clears the single-retry guard.
	preserveMu   sync.Mutex
	lastSnapshot time.Time
	stableTimer  *time.Timer
}

func NewWhatsAppClient(dataDir, notificationsDir, instance string, readOnly bool, noNotify bool, skipSenders map[string]bool, logger waLog.Logger) (*WhatsAppClient, error) {
	store, err := NewMessageStore(dataDir)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize message store: %v", err)
	}

	dbLog := logger.Sub("Database")
	whatsappDBPath := filepath.Join(dataDir, "whatsapp.db")

	container, err := sqlstore.New(context.Background(), "sqlite3", fmt.Sprintf("file:%s?_foreign_keys=on&_journal_mode=WAL&_busy_timeout=30000", whatsappDBPath), dbLog)
	if err != nil {
		store.Close()
		return nil, fmt.Errorf("failed to connect to whatsapp database: %v", err)
	}

	deviceStore, err := container.GetFirstDevice(context.Background())
	if err != nil {
		if err == sql.ErrNoRows {
			deviceStore = container.NewDevice()
			logger.Infof("Created new device")
		} else {
			store.Close()
			return nil, fmt.Errorf("failed to get device: %v", err)
		}
	}

	// Enable full history sync (up to 2 years) for deeper backfill on new QR pairing
	waStore.DeviceProps.RequireFullSync = proto.Bool(true)
	waStore.DeviceProps.HistorySyncConfig.FullSyncDaysLimit = proto.Uint32(730)
	waStore.DeviceProps.HistorySyncConfig.FullSyncSizeMbLimit = proto.Uint32(2048)
	waStore.DeviceProps.HistorySyncConfig.RecentSyncDaysLimit = proto.Uint32(730)
	waStore.DeviceProps.HistorySyncConfig.SupportGroupHistory = proto.Bool(true)

	// Ban-avoidance: present as a real Chrome-on-Linux client instead of
	// whatsmeow's giveaway default Os="whatsmeow"/PlatformType=UNKNOWN. A lazy
	// fingerprint tell; not sufficient alone (behaviour dominates), but free.
	waStore.SetOSInfo("Linux", waStore.GetWAVersion())
	waStore.DeviceProps.PlatformType = waCompanionReg.DeviceProps_CHROME.Enum()

	client := whatsmeow.NewClient(deviceStore, logger)
	if client == nil {
		store.Close()
		return nil, fmt.Errorf("failed to create WhatsApp client")
	}
	// whatsmeow otherwise labels automatic delivery receipts as "inactive" until
	// presence has successfully gone online. Official clients don't render those
	// receipts as a second tick, and a freshly provisioned account may not have a
	// push name yet (which makes SendPresence fail). A writable agent is actively
	// consuming messages, so its delivery receipts must always be visible.
	client.SetForceActiveDeliveryReceipts(forceActiveDeliveryReceipts(readOnly))

	state := newStateStore(dataDir)
	managed := newManagedAuth(loadManagedConfig())
	boxLinker := chooseLinker(managed.cfg, state)
	wac := &WhatsAppClient{
		client:           client,
		store:            store,
		logger:           logger,
		dataDir:          dataDir,
		notificationsDir: notificationsDir,
		instance:         instance,
		readOnly:         readOnly,
		noNotify:         noNotify,
		skipSenders:      skipSenders,
		messageSenders:   make(map[string]string),
		state:            state,
		linker:           boxLinker,
		authStatus:       AuthStatusNotAuthenticated,
		transcribeSem:    make(chan struct{}, MaxConcurrentTranscriptions),
		readQueue:        make(map[string]*chatReadBatch),
		msgWork:          make(chan func(), MsgWorkBuffer),
		workerDone:       make(chan struct{}),
	}
	// Keep the doubletick client at the edge in every mode. Managed linkers reuse
	// their reconciled client; QR mode still needs the config to inspect egress and,
	// when credentials exist, lease residential egress before connecting.
	wac.managed = managed
	if ml, ok := boxLinker.(*managedLinker); ok {
		wac.managed = ml.auth
	}

	client.AddEventHandler(wac.eventHandler)
	go wac.runMsgWorker()

	return wac, nil
}

func forceActiveDeliveryReceipts(readOnly bool) bool { return !readOnly }

// runMsgWorker drains the data-plane work queue on a single goroutine, so
// message/receipt handlers keep per-chat FIFO order while running off
// whatsmeow's serial node-handler loop. Stopped by Disconnect via workerDone.
func (wac *WhatsAppClient) runMsgWorker() {
	for {
		select {
		case <-wac.workerDone:
			return
		case fn := <-wac.msgWork:
			fn()
		}
	}
}

// enqueueWork hands a data-plane handler to the worker, falling back to running
// it inline when the queue is full (bounded memory; backpressure only under a
// sustained flood).
func (wac *WhatsAppClient) enqueueWork(fn func()) {
	select {
	case wac.msgWork <- fn:
	default:
		fn()
	}
}

type egressInfo struct {
	Query   string `json:"query"`
	Status  string `json:"status"`
	Message string `json:"message"`
	Hosting bool   `json:"hosting"`
	Proxy   bool   `json:"proxy"`
	Mobile  bool   `json:"mobile"`
}

var lookupEgress = inspectEgress

func inspectEgress(proxyURL string) (egressInfo, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if proxyURL != "" {
		parsed, err := url.Parse(proxyURL)
		if err != nil {
			return egressInfo{}, fmt.Errorf("parse proxy URL: %w", err)
		}
		transport.Proxy = http.ProxyURL(parsed)
	}
	client := &http.Client{Timeout: 10 * time.Second, Transport: transport}
	resp, err := client.Get("http://ip-api.com/json?fields=status,message,query,hosting,proxy,mobile")
	if err != nil {
		return egressInfo{}, fmt.Errorf("query egress IP intelligence: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return egressInfo{}, fmt.Errorf("query egress IP intelligence: HTTP %d", resp.StatusCode)
	}
	var out egressInfo
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return egressInfo{}, fmt.Errorf("decode egress IP intelligence: %w", err)
	}
	if out.Status != "success" {
		return egressInfo{}, fmt.Errorf("query egress IP intelligence: %s", out.Message)
	}
	return out, nil
}

func datacenterEgress(info egressInfo) bool {
	// ip-api has no separate residential boolean. A non-hosting exit is either
	// mobile or inferred to be residential broadband. A residential lease may
	// legitimately set proxy=true, so hosting is the hard datacenter signal.
	return info.Hosting
}

// ensureManagedProxy selects and validates companion egress before Connect. Explicit
// bring-your-own proxy wins, managed mode leases automatically, and an otherwise
// direct connection is inspected and upgraded to a lease if it is a datacenter exit.
// Every selected path is inspected through that path. Managed and proxy paths fail
// closed when inspection is unavailable; plain QR boxes may connect with a warning.
func (wac *WhatsAppClient) ensureManagedProxy() error {
	if wac.managed == nil {
		wac.managed = newManagedAuth(loadManagedConfig())
	}
	wac.proxyMu.Lock()
	defer wac.proxyMu.Unlock()

	selected := wac.managed.cfg.proxyURL
	if selected == "" && wac.managed.usesResidentialProxy() {
		selected = wac.proxyURL
		if selected == "" {
			leased, err := wac.managed.leaseProxy()
			if err != nil {
				return err
			}
			wac.proxyURL = leased
			selected = leased
		}
	}
	info, cached := wac.egressCache[selected]
	var err error
	if !cached {
		info, err = lookupEgress(selected)
		if err != nil {
			if selected == "" && !wac.managed.isHosted() {
				wac.logger.Warnf("Could not inspect direct WhatsApp egress; proceeding with plain QR connection: %v", err)
				return nil
			}
			return fmt.Errorf("cannot verify safe WhatsApp egress; obtain a residential proxy and set WHATSAPP_PROXY_URL: %w", err)
		}
	}
	if selected == "" && datacenterEgress(info) {
		if !wac.managed.isHosted() {
			return fmt.Errorf("WhatsApp egress IP %s is a datacenter/hosting exit; obtain a residential proxy and set WHATSAPP_PROXY_URL", info.Query)
		}
		leased, err := wac.managed.leaseProxy()
		if err != nil {
			return fmt.Errorf("datacenter egress detected and doubletick could not lease a residential proxy: %w", err)
		}
		wac.proxyURL = leased
		selected = leased
		info, err = lookupEgress(selected)
		if err != nil {
			return fmt.Errorf("cannot verify leased residential proxy; obtain a residential proxy and set WHATSAPP_PROXY_URL: %w", err)
		}
	}
	if datacenterEgress(info) {
		return fmt.Errorf("WhatsApp egress IP %s is still a datacenter/hosting exit; obtain a residential proxy and set WHATSAPP_PROXY_URL", info.Query)
	}
	if wac.egressCache == nil {
		wac.egressCache = make(map[string]egressInfo)
	}
	wac.egressCache[selected] = info
	if selected != "" {
		if err := wac.client.SetProxyAddress(selected); err != nil {
			return fmt.Errorf("apply residential proxy: %w", err)
		}
	}
	return nil
}

// Connect is the daemon's boot connection step. Its whole job is to maintain a
// LINKED device: if the device is linked (Store.ID != nil) it connects and keeps
// the session; if it is not linked it stays IDLE (socket up, not connected), never
// auto-pairing. Pairing is only ever a deliberate `whatsapp provision`/`link`
// (foreground, single-flighted), so no background pairing goroutine can race an
// explicit command.
func (wac *WhatsAppClient) Connect() error {
	if wac.client.Store.ID == nil {
		wac.setAuthStatus(AuthStatusNotAuthenticated)
		wac.logger.Infof("No linked device; staying idle. Run `whatsapp connect` to link.")
		return nil
	}

	// A parked posture persists across restarts (state.json). A prior yield to
	// another device stays parked until a deliberate `whatsapp connect` clears it:
	// reconnecting here would steal the session back and ping-pong with the other
	// holder. Hydrate the in-memory mode so every reconnect path (EnsureConnected,
	// recoverOrRestart) refuses too, and stay idle.
	if wac.state.snapshot().ConnParked {
		wac.setConnMode(connParked)
		wac.logger.Infof("Session parked: another device took over. Staying idle; run `whatsapp connect` to re-link.")
		return nil
	}

	// Hard-fail before WhatsApp sees a datacenter exit. The caller surfaces the
	// residential-proxy instruction and must not leave a seemingly healthy daemon.
	if err := wac.ensureManagedProxy(); err != nil {
		return fmt.Errorf("refusing to connect WhatsApp without verified residential egress: %w", err)
	}

	wac.logger.Infof("Device already authenticated, connecting...")
	err := wac.client.Connect()
	if errors.Is(err, whatsmeow.ErrAlreadyConnected) {
		wac.onConnected()
		wac.logger.Infof("Already connected to WhatsApp")
		return nil
	}
	if err != nil {
		// A valid device session plus a transient connect failure must never
		// delete the store; recover under the supervisor instead of re-pairing.
		wac.logger.Warnf("Failed to connect with existing session: %v; attempting recovery", err)
		go wac.recoverOrRestart("connect_failed")
		return nil
	}

	for i := 0; i < ConnectRetryAttempts; i++ {
		time.Sleep(ConnectRetryDelay)
		if wac.client.IsConnected() {
			wac.onConnected()
			wac.logger.Infof("Connected to WhatsApp after %d seconds", i+1)
			return nil
		}
	}

	wac.logger.Warnf("Connection timeout with existing session; attempting recovery")
	go wac.recoverOrRestart("connect_failed")
	return nil
}

// setConnMode records the daemon's connection posture (normal/pairing/parked).
func (wac *WhatsAppClient) setConnMode(m connMode) { wac.mode.Store(int32(m)) }

// connModeIs reports whether the current posture is m.
func (wac *WhatsAppClient) connModeIs(m connMode) bool { return connMode(wac.mode.Load()) == m }

// onConnected is the "connection is healthy and logged in" routine, used on a boot
// connect of an already-linked device: clear any park, mark authenticated, start
// the stale detector, go online. It does NOT touch the post-link sync window.
func (wac *WhatsAppClient) onConnected() {
	wac.setConnMode(connNormal)
	// A successful (re)connect only ever reaches here via boot or a deliberate
	// connect/link, so it is the single point that clears the persisted park.
	wac.state.update(func(s *daemonState) { s.ConnParked = false })
	wac.setAuthStatus(AuthStatusAuthenticated)
	wac.startStaleMessageDetector()
	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status: %v", err)
	}
}

// onLinked is onConnected plus starting the fragile post-link history-sync window.
// Used only on a FRESH link (QR success, managed provision, phone-code PairSuccess),
// never on a routine reconnect, so the window is not re-armed on every reconnect.
func (wac *WhatsAppClient) onLinked() {
	wac.onConnected()
	wac.markLinkedNow()
	// Capture a good-device snapshot of the freshly PAIRED store immediately, bypassing
	// the throttle: the pre-pair events.Connected already snapshotted an unpaired store,
	// so a conflict within SnapshotMinInterval of linking would otherwise restore an
	// unpaired device. This gives recovery a valid restore point from the moment of link.
	wac.snapshotGoodDeviceNow()
}

func (wac *WhatsAppClient) Disconnect() {
	wac.staleMu.Lock()
	if wac.staleDetectorDone != nil {
		close(wac.staleDetectorDone)
		wac.staleDetectorDone = nil
	}
	wac.staleMu.Unlock()

	wac.presenceMutex.Lock()
	wac.presenceActive = false
	wac.presenceMutex.Unlock()

	close(wac.workerDone)
	wac.client.Disconnect()
	wac.store.Close()
}

func (wac *WhatsAppClient) EnsureConnected() error {
	if wac.client.IsConnected() && wac.client.IsLoggedIn() {
		return nil
	}

	wac.connectMutex.Lock()
	defer wac.connectMutex.Unlock()

	if wac.client.IsConnected() && wac.client.IsLoggedIn() {
		return nil
	}

	if wac.client.Store.ID == nil {
		wac.setAuthStatus(AuthStatusNotAuthenticated)
		return fmt.Errorf("WhatsApp is not authenticated. Use 'whatsapp pair-phone --phone <number>' to authenticate")
	}

	// A parked session yielded to another device that took it over. Reconnecting
	// here (from a write command's lazy reconnect) would steal the session back and
	// ping-pong with the other holder, so refuse instead. A deliberate re-link
	// clears the park.
	if wac.connModeIs(connParked) {
		return fmt.Errorf("WhatsApp session parked: another device took over. Re-link with `whatsapp connect`")
	}

	// Never reconnect the cloud companion without the residential egress in place.
	if err := wac.ensureManagedProxy(); err != nil {
		return fmt.Errorf("residential proxy lease required before reconnecting: %w", err)
	}

	wac.logger.Warnf("WhatsApp is not connected. Attempting to reconnect...")
	if err := wac.client.Connect(); err != nil && !errors.Is(err, whatsmeow.ErrAlreadyConnected) {
		return fmt.Errorf("failed to reconnect to WhatsApp: %v", err)
	}

	for i := 0; i < ConnectRetryAttempts; i++ {
		if wac.client.IsConnected() {
			wac.setAuthStatus(AuthStatusAuthenticated)
			return nil
		}
		time.Sleep(ConnectRetryDelay)
	}

	return fmt.Errorf("WhatsApp is not connected. Ensure WhatsApp is authenticated and connected")
}

// recoverOrRestart handles connection-fatal events whatsmeow does not auto-recover
// from (StreamReplaced, StreamError, high-count KeepAliveTimeout, send deadlock). It
// force-drops the socket first, so a deadlocked-but-"connected" client actually
// reconnects instead of short-circuiting on IsConnected, then tries one reconnect; on
// failure it writes the daemon_died marker and exits for the supervisor. No-op while
// parked (would steal the session back) or pairing (which owns the connection). Runs
// in its own goroutine so it does not block the event dispatcher.
func (wac *WhatsAppClient) recoverOrRestart(reason string) {
	if wac.connModeIs(connParked) || wac.connModeIs(connPairing) {
		wac.logger.Infof("Skipping recovery (%s): connection is parked or pairing", reason)
		return
	}
	if wac.client.Store.ID == nil {
		// No linked session to recover (fresh box, mid-pairing, or logged out).
		// Recovery exists to reconnect a LINKED session; exiting here would abort an
		// in-flight pairing (e.g. the phone-code enter-the-code window, where the
		// client is connected but Store.ID is still nil) for nothing.
		wac.logger.Infof("Skipping recovery (%s): no linked device", reason)
		return
	}
	wac.logger.Warnf("Connection-fatal event (%s); forcing a reconnect", reason)
	// Drop the (possibly wedged) socket so EnsureConnected does real work instead
	// of returning early on a stale IsConnected.
	wac.client.Disconnect()
	if err := wac.EnsureConnected(); err == nil {
		wac.logger.Infof("Reconnected after %s", reason)
		return
	}
	wac.connRecoverOnce.Do(func() {
		wac.logger.Errorf("Reconnect failed after %s; writing death marker and exiting for restart", reason)
		if wac.notificationsDir != "" {
			writeDeathNotification(wac.notificationsDir, "connection_lost:"+reason)
		}
		// Best-effort exit. The unix socket is removed by startSocketServer on
		// the next daemon boot, so skipping the deferred socket cleanup is safe.
		os.Exit(1)
	})
}

func (wac *WhatsAppClient) EnsureOnline() error {
	// Read-only instances never broadcast presence, so the linked account
	// does not appear online to its contacts.
	if wac.readOnly {
		return nil
	}
	wac.presenceMutex.Lock()
	defer wac.presenceMutex.Unlock()

	if !wac.presenceActive {
		err := wac.client.SendPresence(context.Background(), types.PresenceAvailable)
		if err != nil {
			return fmt.Errorf("failed to set online status: %v", err)
		}
		wac.presenceActive = true
		wac.logger.Debugf("Set online status")
	}
	return nil
}

// beginPairing single-flights a pairing operation: acquire pairMu (ok=false when
// another pairing holds it) and mark the connection pairing so recovery leaves it
// alone. release restores the normal posture (unless a yield parked it mid-pairing)
// and frees the lock. Every pairing entry point goes through this, so none race.
func (wac *WhatsAppClient) beginPairing() (release func(), ok bool) {
	if !wac.pairMu.TryLock() {
		return nil, false
	}
	wac.setConnMode(connPairing)
	return func() {
		wac.mode.CompareAndSwap(int32(connPairing), int32(connNormal))
		wac.pairMu.Unlock()
	}, true
}

// clearQR drops any live QR code/image so a finished or abandoned link session
// leaves no stale artifact for the link page to serve.
func (wac *WhatsAppClient) clearQR() {
	wac.authMutex.Lock()
	defer wac.authMutex.Unlock()
	if wac.qrPath != "" {
		os.Remove(wac.qrPath)
		wac.qrPath = ""
	}
	wac.currentQRCode = ""
}

// runQRLink is the whole self-hosted QR pairing, run synchronously in the socket
// command: serve the scan page (when port > 0), then loop GetQRChannel -> Connect ->
// consume rotating codes, re-arming after each batch until the user scans or the
// window elapses. Self-contained: it leaves the client disconnected on failure so
// the next `whatsapp link` starts clean (never GetQRChannel-on-connected-client).
func (wac *WhatsAppClient) runQRLink(port int) (linkResult, error) {
	if port > 0 {
		wac.startLinkServer(port)
		defer wac.stopLinkServer()
	}
	defer wac.clearQR()

	// On a cloud box the companion (including a user-owned BYO link) egresses through
	// the residential proxy; a no-op on a self-hosted box.
	if err := wac.ensureManagedProxy(); err != nil {
		return linkResult{}, err
	}

	deadline := time.Now().Add(LinkSessionTimeout)
	for time.Now().Before(deadline) {
		qrChan, err := wac.client.GetQRChannel(context.Background())
		if err != nil {
			wac.client.Disconnect()
			return linkResult{}, fmt.Errorf("open QR channel: %w", err)
		}
		if err := wac.client.Connect(); err != nil {
			wac.client.Disconnect()
			return linkResult{}, fmt.Errorf("connect for QR: %w", err)
		}
		if wac.consumeQRChannel(qrChan) {
			return linkResult{}, nil // linked the user's own account (no msisdn)
		}
		// Codes exhausted without a scan; drop the socket and re-arm a fresh batch.
		wac.client.Disconnect()
	}
	return linkResult{}, fmt.Errorf("no device linked within %s; retry `whatsapp connect` when the user is ready", LinkSessionTimeout)
}

// consumeQRChannel drains one QR channel, publishing each rotated code to disk and
// memory. Returns true on pairing success, false when the channel closes without
// success (whatsmeow closes it after the last code times out).
func (wac *WhatsAppClient) consumeQRChannel(qrChan <-chan whatsmeow.QRChannelItem) bool {
	for evt := range qrChan {
		if evt.Event == "code" {
			qrPath := filepath.Join(wac.dataDir, "qr-code.png")
			if err := qrcode.WriteFile(evt.Code, qrcode.Medium, QRCodeSize, qrPath); err != nil {
				wac.logger.Errorf("Failed to save QR code: %v", err)
				continue
			}
			wac.authMutex.Lock()
			wac.qrPath = qrPath
			wac.currentQRCode = evt.Code
			wac.authMutex.Unlock()
			wac.setAuthStatus(AuthStatusQRReady)
			wac.logger.Infof("QR code saved to %s", qrPath)
		} else if evt.Event == "success" {
			wac.logger.Infof("Successfully authenticated!")
			wac.clearQR()
			wac.onLinked()
			return true
		}
	}
	return false
}

// generatePairCode brings the WS up (if needed) and mints a phone pairing code for
// the user to enter. The client stays connected afterward so whatsmeow's PairSuccess
// event (handled in eventHandler) finishes the link once the user enters the code.
func (wac *WhatsAppClient) generatePairCode(phone string) (string, error) {
	if !wac.client.IsConnected() {
		if err := wac.client.Connect(); err != nil && !errors.Is(err, whatsmeow.ErrAlreadyConnected) {
			return "", fmt.Errorf("connect for pairing: %w", err)
		}
	}
	if !wac.client.IsConnected() {
		return "", fmt.Errorf("WhatsApp websocket not connected; retry `whatsapp pair-phone` in a moment")
	}
	// The socket is up and the pairing request is about to go to WhatsApp: record the
	// attempt on dispatch, before awaiting the response, so a request that reaches
	// WhatsApp but errors mid-handshake still burns a ban-avoidance slot. The caller
	// (cmdPairPhone) owns the pre-mint cap CHECK; a pre-dispatch failure records none.
	wac.state.recordPairAttempt(time.Now())
	return wac.PairPhone(phone)
}

// setAuthStatus updates the in-memory verdict and persists a meaningful one (via
// the state store) so a cold read stays truthful. A successful connect/link clears a
// stale logged_out note a prior LoggedOut event left behind. The transient
// not_authenticated default is NOT persisted: it must not clobber a recorded
// logged_out reason (the logout handler owns that), and an unwritten status reads
// back as not_started.
func (wac *WhatsAppClient) setAuthStatus(status AuthStatus) {
	wac.authMutex.Lock()
	wac.authStatus = status
	wac.authMutex.Unlock()
	if status == AuthStatusNotAuthenticated {
		return
	}
	wac.state.update(func(s *daemonState) {
		s.AuthStatus = string(status)
		s.AuthNote = ""
	})
}

func (wac *WhatsAppClient) GetAuthStatus() AuthStatus {
	wac.authMutex.RLock()
	defer wac.authMutex.RUnlock()
	return wac.authStatus
}

func (wac *WhatsAppClient) IsAuthenticated() bool {
	return wac.GetAuthStatus() == AuthStatusAuthenticated
}

// markLinkedNow starts (or extends) the post-link history-sync window.
func (wac *WhatsAppClient) markLinkedNow() {
	wac.state.update(func(s *daemonState) { s.LinkedAt = time.Now() })
}

func (wac *WhatsAppClient) PairPhone(phone string) (string, error) {
	phone = strings.TrimPrefix(phone, "+")

	// The WS to WhatsApp must be up before requesting a pairing code. The caller
	// (generatePairCode / managed provision) has already initiated Connect; wait
	// briefly for it to land, then return a friendly error if it never does.
	for i := 0; i < ConnectRetryAttempts; i++ {
		if wac.client.IsConnected() {
			break
		}
		time.Sleep(ConnectRetryDelay)
	}
	if !wac.client.IsConnected() {
		return "", fmt.Errorf("WhatsApp websocket not connected; restart the daemon and retry")
	}

	code, err := wac.client.PairPhone(context.Background(), phone, true, whatsmeow.PairClientChrome, "Chrome (Linux)")
	if err != nil {
		return "", err
	}
	if len(code) == 8 {
		code = code[:4] + "-" + code[4:]
	}
	return code, nil
}

func (wac *WhatsAppClient) startStaleMessageDetector() {
	wac.staleMu.Lock()
	defer wac.staleMu.Unlock()
	if wac.staleDetectorDone != nil {
		return
	}
	wac.staleDetectorDone = make(chan struct{})
	done := wac.staleDetectorDone
	go func() {
		ticker := time.NewTicker(StaleCheckInterval)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				staleIDs, err := wac.store.GetStaleOutgoingMessages(StaleMessageThreshold)
				if err != nil {
					wac.logger.Warnf("Failed to check for stale messages: %v", err)
					continue
				}
				if len(staleIDs) > 0 {
					// No delivery receipt arrived within StaleMessageThreshold.
					// This is usually slow recipient connectivity or read-receipts-off,
					// not actual filtering by WhatsApp. UpdateDeliveryStatus will
					// self-heal the status field if a receipt arrives later, so we
					// only mark + log here, no notification firing.
					wac.logger.Warnf("Marking %d outgoing messages as unconfirmed (no delivery receipt within %v): %v", len(staleIDs), StaleMessageThreshold, staleIDs)
					if err := wac.store.MarkMessagesUnconfirmed(staleIDs); err != nil {
						wac.logger.Warnf("Failed to mark messages as unconfirmed: %v", err)
					}
				}
			}
		}
	}()
}

// normalizeToJPEG returns WhatsApp-ready JPEG bytes: it passes an already-JPEG
// input through untouched and re-encodes any other decodable image (e.g. PNG)
// to JPEG. WhatsApp rejects non-JPEG profile pictures, so a raw upload of a
// different format must be converted before it is sent.
func normalizeToJPEG(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("image is empty")
	}
	// JPEG magic bytes (FF D8 FF): already JPEG, send unchanged.
	if len(data) >= 3 && data[0] == 0xFF && data[1] == 0xD8 && data[2] == 0xFF {
		return data, nil
	}
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("image must be JPEG or a decodable format (e.g. PNG): %w", err)
	}
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: 90}); err != nil {
		return nil, fmt.Errorf("failed to encode image as JPEG: %w", err)
	}
	return buf.Bytes(), nil
}

// SetProfilePhoto sets the agent's own WhatsApp profile picture from the
// companion client (no phone driving), the same multi-device path WhatsApp Web
// uses: an IQ set to namespace w:profile:picture targeting the own (non-AD) JID,
// carrying the JPEG bytes. WhatsApp wants a roughly square ~640x640 JPEG; the
// caller supplies a suitable image (non-JPEG inputs are re-encoded, not resized).
func (wac *WhatsAppClient) SetProfilePhoto(imageBytes []byte) error {
	jpegBytes, err := normalizeToJPEG(imageBytes)
	if err != nil {
		return err
	}
	if err := wac.EnsureConnected(); err != nil {
		return err
	}
	if wac.client.Store.ID == nil {
		return fmt.Errorf("WhatsApp is not authenticated")
	}
	// The OWN profile picture carries NO `target` attribute (unlike a group photo,
	// which targets the group JID): the server infers "self", and a self-target is
	// silently dropped. To=ServerJID, one `picture type=image` node, verified live.
	_, err = wac.client.DangerousInternals().SendIQ(context.Background(), whatsmeow.DangerousInfoQuery{
		Namespace: "w:profile:picture",
		Type:      "set",
		To:        types.ServerJID,
		Content: []waBinary.Node{{
			Tag:     "picture",
			Attrs:   waBinary.Attrs{"type": "image"},
			Content: jpegBytes,
		}},
	})
	if err != nil {
		return fmt.Errorf("failed to set profile photo: %w", err)
	}
	return nil
}

// RemoveProfilePhoto removes the account's own profile picture. An empty
// w:profile:picture set is WhatsApp's removal operation; as with setting the own
// photo, it must not carry a target attribute.
func (wac *WhatsAppClient) RemoveProfilePhoto() error {
	if err := wac.EnsureConnected(); err != nil {
		return err
	}
	if wac.client.Store.ID == nil {
		return fmt.Errorf("WhatsApp is not authenticated")
	}
	_, err := wac.client.DangerousInternals().SendIQ(context.Background(), ownProfilePictureIQ(nil))
	if err != nil {
		return fmt.Errorf("failed to remove profile photo: %w", err)
	}
	return nil
}

// ownProfilePictureIQ builds the account-self picture mutation. A nil avatar is
// intentionally represented by nil content: that is the idempotent remove form.
func ownProfilePictureIQ(avatar []byte) whatsmeow.DangerousInfoQuery {
	var content any
	if avatar != nil {
		content = []waBinary.Node{{
			Tag:     "picture",
			Attrs:   waBinary.Attrs{"type": "image"},
			Content: avatar,
		}}
	}
	return whatsmeow.DangerousInfoQuery{
		Namespace: "w:profile:picture",
		Type:      "set",
		To:        types.ServerJID,
		Content:   content,
	}
}

// SetProfileName sets the agent's own WhatsApp display name (push name). The
// account-wide name goes through an app-state mutation (setting_pushName, the path
// WhatsApp Web uses), which needs the app-state keys the primary shares on link. A
// managed/bare number often has none yet, so that leg is best-effort: the LOCAL push
// name set below is what presence (online, typing, read receipts) actually requires,
// so it is set regardless. Without it a freshly-registered number can never broadcast
// presence ("can't send presence without PushName set") and shows no online/read state.
func (wac *WhatsAppClient) SetProfileName(name string) error {
	if strings.TrimSpace(name) == "" {
		return fmt.Errorf("name is required")
	}
	if err := wac.EnsureConnected(); err != nil {
		return err
	}
	if err := wac.client.SendAppState(context.Background(), appstate.BuildSettingPushName(name)); err != nil {
		wac.logger.Warnf("set-profile-name: account-wide name skipped (no app-state keys yet, normal for a fresh managed number): %v", err)
	}
	wac.client.Store.PushName = name
	if err := wac.client.Store.Save(context.Background()); err != nil {
		return fmt.Errorf("failed to persist push name: %w", err)
	}
	if err := wac.client.SendPresence(context.Background(), types.PresenceAvailable); err != nil {
		wac.logger.Warnf("set-profile-name: name set locally, but broadcasting presence failed: %v", err)
	}
	return nil
}
