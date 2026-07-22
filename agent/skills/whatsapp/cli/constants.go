package main

import (
	"math/rand/v2"
	"strings"
	"time"
)

const (
	MaxFileSizeBytes  = 100 * 1024 * 1024
	MaxAudioSizeBytes = 16 * 1024 * 1024

	ConnectRetryAttempts = 10
	ConnectRetryDelay    = 1 * time.Second

	// ReExecSettleDelay holds the daemon after it drops the old socket, before a
	// preserve-reconnect re-exec, so WhatsApp registers the old server-side session's
	// teardown first. Re-execing straight into a still-live session is what makes the
	// server fire a fresh "logged out from another device" (401) conflict, which
	// churned a freshly-linked companion to unpaired. A short settle removes that
	// overlap so the re-exec'd process reconnects onto a clean session.
	ReExecSettleDelay = 5 * time.Second

	// ManagedLinkTimeout bounds the wait for whatsmeow to register the companion
	// link after the control plane has accepted the pairing code (POST /pair is
	// synchronous, so this is just the PairSuccess round-trip). Well inside
	// SocketTimeout so a synchronous `provision` never outlives its socket call.
	ManagedLinkTimeout = 60 * time.Second

	// KeepAliveRestartThreshold is the consecutive keep-alive failure count at
	// which the socket is treated as dead. Below it, whatsmeow is still
	// retrying and will emit KeepAliveRestored on recovery, so we wait.
	KeepAliveRestartThreshold = 5

	StaleCheckInterval    = 10 * time.Minute
	StaleMessageThreshold = 4 * time.Hour

	MaxSenderCacheSize    = 10_000
	SenderCacheEvictBatch = 2_000

	// MsgWorkBuffer bounds the data-plane work queue that keeps message/receipt
	// handling off whatsmeow's serial node loop. A full queue falls back to inline
	// handling (bounded memory, backpressure only under a sustained flood).
	MsgWorkBuffer = 512

	QRCodeSize                  = 256
	MaxConcurrentTranscriptions = 3

	TypingDelayPerChar = 25 * time.Millisecond
	TypingDelayMin     = 1500 * time.Millisecond
	TypingDelayMax     = 6 * time.Second

	ReadDelayPerChar = 40 * time.Millisecond
	ReadDelayBase    = 1500 * time.Millisecond
	ReadDelayMax     = 8 * time.Second

	ReactionDelayMin = 400 * time.Millisecond
	ReactionDelayMax = 700 * time.Millisecond
	PreSendDelayMin  = 250 * time.Millisecond

	PreSendDelayMax = 400 * time.Millisecond

	// SendTimeout bounds one SendMessage round-trip. The daemon's known
	// deadlock ("Node handling is taking long", sends hang forever) surfaces
	// as this timeout, which triggers one safe reconnect via recoverOrRestart.
	SendTimeout = 60 * time.Second

	RapidMessageThreshold  = 3 * time.Second
	PresenceVarianceFactor = 0.2

	SocketTimeout     = 5 * time.Minute
	SocketDialTimeout = 2 * time.Second

	// The blocking pairing commands run the whole handshake in one socket call, so
	// their socket deadline must exceed the WORST-CASE pairing window. LinkSocketTimeout
	// clears LinkSessionTimeout (10m). ProvisionSocketTimeout must clear the full
	// managed stack: claim-poll (provisionPollMax*provisionPollInterval ~180s) + the
	// server-synchronous /pair (controlHTTPTimeout 180s) + the link wait
	// (ManagedLinkTimeout 60s) ~= 420s; 9m leaves margin so a slow-but-valid provision
	// is never cut off with a spurious "daemon not answering". Both bound a single
	// command's connection, not the daemon.
	LinkSocketTimeout      = LinkSessionTimeout + time.Minute
	ProvisionSocketTimeout = 9 * time.Minute

	DeliveryStatusSent        = "sent"
	DeliveryStatusDelivered   = "delivered"
	DeliveryStatusRead        = "read"
	DeliveryStatusPlayed      = "played"
	DeliveryStatusUnconfirmed = "unconfirmed"

	MediaTypeImage    = "image"
	MediaTypeVideo    = "video"
	MediaTypeAudio    = "audio"
	MediaTypeDocument = "document"

	DefaultWhisperModelPath = "/usr/local/share/ggml-small.bin"
)

var shellEscapeReplacer = strings.NewReplacer(
	`\!`, `!`, `\?`, `?`, `\.`, `.`, `\-`, `-`,
	`\(`, `(`, `\)`, `)`, `\#`, `#`,
)

// humanDelay computes a human-like delay: base + perUnit*units, clamped to
// maxDelay, then applies ±20% random variance.
func humanDelay(base, perUnit time.Duration, units int, maxDelay time.Duration) time.Duration {
	d := base + perUnit*time.Duration(units)
	if d > maxDelay {
		d = maxDelay
	}
	variance := int(float64(d.Milliseconds()) * PresenceVarianceFactor)
	if variance > 0 {
		d += time.Duration(rand.IntN(variance*2)-variance) * time.Millisecond
	}
	return d
}

func randomDelay(lo, hi time.Duration) time.Duration {
	spread := hi - lo
	if spread <= 0 {
		return lo
	}
	return lo + time.Duration(rand.Int64N(int64(spread)))
}
