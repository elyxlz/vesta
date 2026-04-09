package main

import (
	"math/rand/v2"
	"strings"
	"time"
)

// File size limits.
const (
	MaxFileSizeBytes  = 100 * 1024 * 1024 // 100 MB
	MaxAudioSizeBytes = 16 * 1024 * 1024  // 16 MB (WhatsApp limit)
)

// Connection and reconnection.
const (
	ConnectRetryAttempts = 10
	ConnectRetryDelay    = 1 * time.Second
)

// Stale message detection.
const (
	StaleCheckInterval    = 30 * time.Second
	StaleMessageThreshold = 90 * time.Second
)

// Sender cache (maps message IDs to sender JIDs for reaction routing).
const (
	MaxSenderCacheSize    = 10_000
	SenderCacheEvictBatch = 2_000 // evict 20% at a time to avoid per-message slice copies
)

// QR code generation.
const QRCodeSize = 256

// Maximum concurrent audio transcription goroutines.
const MaxConcurrentTranscriptions = 3

// Human-like presence simulation — typing indicator.
const (
	TypingDelayPerChar = 25 * time.Millisecond
	TypingDelayMin     = 1500 * time.Millisecond
	TypingDelayMax     = 6 * time.Second
)

// Human-like presence simulation — read receipts.
const (
	ReadDelayPerChar = 40 * time.Millisecond
	ReadDelayBase    = 1500 * time.Millisecond
	ReadDelayMax     = 8 * time.Second
)

// Human-like presence simulation — reaction / pre-send pauses.
const (
	ReactionDelayMin = 400 * time.Millisecond
	ReactionDelayMax = 700 * time.Millisecond
	PreSendDelayMin  = 250 * time.Millisecond
	PreSendDelayMax  = 400 * time.Millisecond
)

// Rapid message threshold — skip presence delays when messages are sent in quick succession.
const RapidMessageThreshold = 3 * time.Second

// Presence delay variance factor applied to computed delays (±20%).
const PresenceVarianceFactor = 0.2

// Socket server timeouts.
const (
	SocketTimeout     = 5 * time.Minute
	SocketDialTimeout = 2 * time.Second
)

// Delivery status progression: sent → delivered → read → played.
const (
	DeliveryStatusSent      = "sent"
	DeliveryStatusDelivered = "delivered"
	DeliveryStatusRead      = "read"
	DeliveryStatusPlayed    = "played"
)

// Media type identifiers.
const (
	MediaTypeImage    = "image"
	MediaTypeVideo    = "video"
	MediaTypeAudio    = "audio"
	MediaTypeDocument = "document"
)

// Whisper model default path.
const DefaultWhisperModelPath = "/usr/local/share/ggml-small.bin"

var shellEscapeReplacer = strings.NewReplacer(
	`\!`, `!`,
	`\?`, `?`,
	`\.`, `.`,
	`\-`, `-`,
	`\(`, `(`,
	`\)`, `)`,
	`\#`, `#`,
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

// randomDelay returns a uniformly random duration between lo and hi.
func randomDelay(lo, hi time.Duration) time.Duration {
	spread := hi - lo
	if spread <= 0 {
		return lo
	}
	return lo + time.Duration(rand.Int64N(int64(spread)))
}
