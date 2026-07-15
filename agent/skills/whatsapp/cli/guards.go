package main

import (
	"fmt"
	"time"
)

// Repeated pairing attempts from a datacenter IP are what get WhatsApp numbers
// auto-flagged and put under review, so pairing is hard rate-limited and the
// fragile post-link history-sync window blocks daemon restarts (restarting
// inside it makes WhatsApp log the device out).
//
// These are the pure decision functions over the pairing-attempt window and the
// sync window; the state they read/write lives in the state store (state.go).
const (
	MaxPairAttempts    = 2
	PairAttemptWindow  = time.Hour
	SyncWindowDuration = 5 * time.Minute
	LinkSessionTimeout = 10 * time.Minute
)

// liveAttempts returns the attempts still inside the rate-limit window.
func liveAttempts(attempts []time.Time, now time.Time) []time.Time {
	var live []time.Time
	for _, attempt := range attempts {
		if now.Sub(attempt) < PairAttemptWindow {
			live = append(live, attempt)
		}
	}
	return live
}

// pairAttemptsInWindow counts the live attempts.
func pairAttemptsInWindow(attempts []time.Time, now time.Time) int {
	return len(liveAttempts(attempts, now))
}

// checkPairAttempt reports whether another pairing attempt is allowed under the
// rate limit, given the already-filtered live attempts. It records nothing: callers
// that can fail before a code is really produced (phone-code pairing, where
// whatsmeow rejects PairPhone until the websocket is up) check first and record
// only on success, so a transient pre-connection failure never burns a slot.
func checkPairAttempt(live []time.Time, now time.Time, acknowledged bool) error {
	if len(live) >= MaxPairAttempts && !acknowledged {
		oldest := live[0]
		for _, attempt := range live {
			if attempt.Before(oldest) {
				oldest = attempt
			}
		}
		cooldown := (PairAttemptWindow - now.Sub(oldest)).Round(time.Minute)
		return fmt.Errorf(
			"pairing blocked for %s: %d pairing attempts in the last hour. Repeated pairing attempts get WhatsApp numbers flagged and banned. Wait out the cooldown and only retry with the user's explicit go-ahead; pass --acknowledge-ban-risk to override",
			cooldown, len(live))
	}
	return nil
}

// syncWindowRemaining reports how much of the post-link sync window is left, given
// when the device last linked (zero time = never linked).
func syncWindowRemaining(linkedAt, now time.Time) time.Duration {
	if linkedAt.IsZero() {
		return 0
	}
	remaining := SyncWindowDuration - now.Sub(linkedAt)
	if remaining < 0 {
		return 0
	}
	return remaining
}
