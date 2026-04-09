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

	StaleCheckInterval    = 30 * time.Second
	StaleMessageThreshold = 90 * time.Second

	MaxSenderCacheSize    = 10_000
	SenderCacheEvictBatch = 2_000

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
	PreSendDelayMax  = 400 * time.Millisecond

	RapidMessageThreshold  = 3 * time.Second
	PresenceVarianceFactor = 0.2

	SocketTimeout     = 5 * time.Minute
	SocketDialTimeout = 2 * time.Second

	DeliveryStatusSent      = "sent"
	DeliveryStatusDelivered = "delivered"
	DeliveryStatusRead      = "read"
	DeliveryStatusPlayed    = "played"

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
