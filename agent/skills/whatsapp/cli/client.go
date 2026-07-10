// Package main implements a WhatsApp CLI and daemon built on whatsmeow.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
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
	authStatus       AuthStatus
	authMutex        sync.RWMutex
	qrPath           string
	currentQRCode    string // guarded by authMutex, cleared on success
	reauthInProgress bool
	// pairGuardMu serializes guardPairAttempt across concurrent link/pair
	// callers so two can't read the same under-limit count and double-spend.
	pairGuardMu       sync.Mutex
	linkMu            sync.Mutex
	linkActive        bool
	linkServer        *http.Server
	linkGeneration    int
	linkTimer         *time.Timer
	presenceActive    bool
	presenceMutex     sync.RWMutex
	lastMessageSentAt time.Time
	connectMutex      sync.Mutex
	connRecoverOnce   sync.Once
	staleDetectorDone chan struct{}
	transcribeSem     chan struct{} // limits concurrent audio transcriptions
	readQueueMu       sync.Mutex
	readQueue         map[string]*chatReadBatch // keyed by chatJID|senderJID; coalesces read receipts in order
	callMgr           *CallManager              // live voice calling; set in serve after Connect, nil for one-shot clients
}

func NewWhatsAppClient(dataDir, notificationsDir, instance string, readOnly bool, noNotify bool, skipSenders map[string]bool, logger waLog.Logger) (*WhatsAppClient, error) {
	store, err := NewMessageStore(dataDir)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize message store: %v", err)
	}

	dbLog := waLog.Stdout("Database", "INFO", true)
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

	client := whatsmeow.NewClient(deviceStore, logger)
	if client == nil {
		store.Close()
		return nil, fmt.Errorf("failed to create WhatsApp client")
	}

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
		authStatus:       AuthStatusNotAuthenticated,
		transcribeSem:    make(chan struct{}, MaxConcurrentTranscriptions),
		readQueue:        make(map[string]*chatReadBatch),
	}

	client.AddEventHandler(wac.eventHandler)

	return wac, nil
}

func (wac *WhatsAppClient) Connect() error {
	if wac.client.Store.ID == nil {
		wac.setAuthStatus(AuthStatusNotAuthenticated)
		go wac.handleQRAuthentication()
		return nil
	}

	wac.logger.Infof("Device already authenticated, connecting...")
	err := wac.client.Connect()
	if errors.Is(err, whatsmeow.ErrAlreadyConnected) {
		wac.setAuthStatus(AuthStatusAuthenticated)
		wac.logger.Infof("Already connected to WhatsApp")
		wac.startStaleMessageDetector()
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
			wac.setAuthStatus(AuthStatusAuthenticated)
			wac.logger.Infof("Connected to WhatsApp after %d seconds", i+1)
			wac.startStaleMessageDetector()
			if err := wac.EnsureOnline(); err != nil {
				wac.logger.Warnf("Failed to set online status: %v", err)
			}
			return nil
		}
	}

	wac.logger.Warnf("Connection timeout with existing session; attempting recovery")
	go wac.recoverOrRestart("connect_failed")
	return nil
}

func (wac *WhatsAppClient) Disconnect() {
	if wac.staleDetectorDone != nil {
		close(wac.staleDetectorDone)
		wac.staleDetectorDone = nil
	}

	wac.presenceMutex.Lock()
	wac.presenceActive = false
	wac.presenceMutex.Unlock()

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

// recoverOrRestart handles connection-fatal events that whatsmeow does not
// auto-recover from: StreamReplaced disables auto-reconnect by design, and a
// StreamError or a high-count KeepAliveTimeout means the socket is dead. It
// tries one active reconnect; if that fails the daemon is alive but deaf
// (receiving nothing, not reconnecting), so it writes the daemon_died marker
// the agent watches for and exits, letting the supervisor start a fresh
// session. Without this the process silently drops every inbound message until
// a manual restart. Runs in its own goroutine so EnsureConnected's retry loop
// does not block the whatsmeow event dispatcher.
func (wac *WhatsAppClient) recoverOrRestart(reason string) {
	wac.logger.Warnf("Connection-fatal event (%s); attempting reconnect", reason)
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

// initiateReauth is the logged-out re-pair path (reached from the LoggedOut
// event, where the device session is genuinely invalid). The pairing guard here
// is the ban protection: WhatsApp logging a device out repeatedly is exactly the
// flag pattern, so a rate-limited re-pair refuses rather than deleting a
// possibly-recoverable store and hammering pairing.
func (wac *WhatsAppClient) initiateReauth() error {
	wac.pairGuardMu.Lock()
	guardErr := guardPairAttempt(wac.dataDir, time.Now(), false)
	wac.pairGuardMu.Unlock()
	if guardErr != nil {
		wac.logger.Warnf("Re-pair after logout refused by pairing guard: %v", guardErr)
		wac.writeAuthStatusFile(map[string]string{
			"status": "logged_out",
			"note":   "pairing rate-limited after repeated logouts, re-link with whatsapp link when the user is ready",
		})
		return nil
	}

	wac.logger.Infof("Initiating re-authentication...")
	wac.client.Disconnect()

	if err := wac.client.Store.Delete(context.Background()); err != nil {
		wac.logger.Errorf("Failed to delete device store: %v", err)
	}

	wac.authMutex.Lock()
	wac.qrPath = ""
	wac.authStatus = AuthStatusNotAuthenticated
	wac.authMutex.Unlock()

	wac.presenceMutex.Lock()
	wac.presenceActive = false
	wac.presenceMutex.Unlock()

	go wac.handleQRAuthentication()
	return nil
}

func (wac *WhatsAppClient) linkModeActive() bool {
	wac.linkMu.Lock()
	defer wac.linkMu.Unlock()
	return wac.linkActive
}

func (wac *WhatsAppClient) startLinkMode(port int) {
	wac.linkMu.Lock()
	wac.linkGeneration++
	generation := wac.linkGeneration
	wac.linkActive = true
	if wac.linkTimer != nil {
		wac.linkTimer.Stop()
	}
	wac.linkTimer = time.AfterFunc(LinkSessionTimeout, func() {
		wac.stopLinkModeGeneration(generation)
	})
	wac.linkMu.Unlock()

	if port > 0 {
		// Shut down any orphaned server from a previous session before binding a new one.
		wac.stopLinkServer()
		wac.startLinkServer(port)
	}
	go wac.handleQRAuthentication()
}

// stopLinkModeGeneration tears down link mode when its session's deadline
// timer fires. A stale generation means a newer session has since started
// and owns linkActive/linkServer, so the old timer must not touch it.
func (wac *WhatsAppClient) stopLinkModeGeneration(generation int) {
	wac.linkMu.Lock()
	if generation != wac.linkGeneration {
		wac.linkMu.Unlock()
		return
	}
	wac.linkActive = false
	if wac.linkTimer != nil {
		wac.linkTimer.Stop()
	}
	wac.linkMu.Unlock()

	wac.stopLinkServer()
	wac.authMutex.Lock()
	wac.currentQRCode = ""
	wac.authMutex.Unlock()
}

func (wac *WhatsAppClient) stopLinkMode() {
	wac.linkMu.Lock()
	wac.linkGeneration++
	wac.linkActive = false
	if wac.linkTimer != nil {
		wac.linkTimer.Stop()
	}
	wac.linkMu.Unlock()

	wac.stopLinkServer()
	wac.authMutex.Lock()
	wac.currentQRCode = ""
	wac.authMutex.Unlock()
}

// consumeQRChannel drains one QR channel, publishing each rotated code to disk
// and memory. Returns true on pairing success, false when the channel closes
// without success (whatsmeow closes it after the last code times out).
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
			wac.authStatus = AuthStatusQRReady
			wac.authMutex.Unlock()
			wac.writeAuthStatusFile(map[string]string{"status": string(AuthStatusQRReady)})
			wac.logger.Infof("QR code saved to %s", qrPath)
		} else if evt.Event == "success" {
			wac.setAuthStatus(AuthStatusAuthenticated)
			wac.logger.Infof("Successfully authenticated!")
			if err := wac.EnsureOnline(); err != nil {
				wac.logger.Warnf("Failed to set online status: %v", err)
			}
			wac.authMutex.Lock()
			if wac.qrPath != "" {
				os.Remove(wac.qrPath)
				wac.qrPath = ""
			}
			wac.currentQRCode = ""
			wac.authMutex.Unlock()
			recordLinkedAt(wac.dataDir, time.Now())
			wac.writeAuthStatusFile(map[string]string{"status": string(AuthStatusAuthenticated)})
			return true
		}
	}
	return false
}

func (wac *WhatsAppClient) handleQRAuthentication() {
	wac.authMutex.Lock()
	if wac.reauthInProgress {
		wac.authMutex.Unlock()
		wac.logger.Infof("QR authentication already in progress, skipping")
		return
	}
	wac.reauthInProgress = true
	defer func() {
		wac.authMutex.Lock()
		wac.reauthInProgress = false
		wac.authMutex.Unlock()
	}()
	wac.authMutex.Unlock()

	for {
		qrChan, err := wac.client.GetQRChannel(context.Background())
		if err != nil {
			wac.logger.Errorf("Failed to get QR channel: %v", err)
			return
		}
		if err := wac.client.Connect(); err != nil {
			wac.logger.Errorf("Failed to connect for QR: %v", err)
			return
		}
		if wac.consumeQRChannel(qrChan) {
			wac.stopLinkMode()
			return
		}
		// Channel closed without success (codes exhausted). While link mode is
		// active, disconnect and re-arm so the link page always shows a live
		// code; a plain unpaired boot gets one pass and stops churning.
		if !wac.linkModeActive() {
			return
		}
		wac.client.Disconnect()
	}
}

func (wac *WhatsAppClient) setAuthStatus(status AuthStatus) {
	wac.authMutex.Lock()
	wac.authStatus = status
	wac.authMutex.Unlock()
}

func (wac *WhatsAppClient) GetAuthStatus() AuthStatus {
	wac.authMutex.RLock()
	defer wac.authMutex.RUnlock()
	return wac.authStatus
}

func (wac *WhatsAppClient) IsAuthenticated() bool {
	return wac.GetAuthStatus() == AuthStatusAuthenticated
}

func (wac *WhatsAppClient) PairPhone(phone string) (string, error) {
	phone = strings.TrimPrefix(phone, "+")

	// The WS to WhatsApp must be up before requesting a pairing code.
	// On first-time pairing Store.ID is nil, so Connect() spawns the QR
	// goroutine asynchronously; calling pair-phone before that goroutine's
	// own client.Connect() lands surfaces "websocket not connected" from
	// whatsmeow. Wait briefly for the WS to come up, then return a
	// friendly error if it never does.
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

func (wac *WhatsAppClient) writeAuthStatusFile(data map[string]string) {
	b, err := json.Marshal(data)
	if err != nil {
		wac.logger.Warnf("Failed to marshal auth status: %v", err)
		return
	}
	if err := os.WriteFile(filepath.Join(wac.dataDir, "auth-status.json"), b, 0644); err != nil {
		wac.logger.Warnf("Failed to write auth status file: %v", err)
	}
}

func (wac *WhatsAppClient) startStaleMessageDetector() {
	if wac.staleDetectorDone != nil {
		return
	}
	wac.staleDetectorDone = make(chan struct{})
	go func() {
		ticker := time.NewTicker(StaleCheckInterval)
		defer ticker.Stop()
		for {
			select {
			case <-wac.staleDetectorDone:
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
