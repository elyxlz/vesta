package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Repeated pairing attempts from a datacenter IP are what get WhatsApp numbers
// auto-flagged and put under review, so pairing is hard rate-limited and the
// fragile post-link history-sync window blocks daemon restarts (restarting
// inside it makes WhatsApp log the device out).
const (
	MaxPairAttempts    = 2
	PairAttemptWindow  = time.Hour
	SyncWindowDuration = 5 * time.Minute
	LinkSessionTimeout = 10 * time.Minute

	pairAttemptsFile = "pairing-attempts.json"
	linkedAtFile     = "linked-at"
)

func loadPairAttempts(dataDir string) []time.Time {
	data, err := os.ReadFile(filepath.Join(dataDir, pairAttemptsFile))
	if err != nil {
		return nil
	}
	var attempts []time.Time
	if err := json.Unmarshal(data, &attempts); err != nil {
		return nil
	}
	return attempts
}

func liveAttempts(attempts []time.Time, now time.Time) []time.Time {
	var live []time.Time
	for _, attempt := range attempts {
		if now.Sub(attempt) < PairAttemptWindow {
			live = append(live, attempt)
		}
	}
	return live
}

func pairAttemptsInWindow(dataDir string, now time.Time) int {
	return len(liveAttempts(loadPairAttempts(dataDir), now))
}

// guardPairAttempt enforces the pairing rate limit, then records the attempt.
func guardPairAttempt(dataDir string, now time.Time, acknowledged bool) error {
	live := liveAttempts(loadPairAttempts(dataDir), now)
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
	live = append(live, now)
	data, err := json.Marshal(live)
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dataDir, pairAttemptsFile), data, 0644)
}

func recordLinkedAt(dataDir string, now time.Time) {
	if err := os.WriteFile(filepath.Join(dataDir, linkedAtFile), []byte(now.UTC().Format(time.RFC3339)), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to record link time: %v\n", err)
	}
}

// syncWindowRemaining reports how much of the post-link sync window is left.
func syncWindowRemaining(dataDir string, now time.Time) time.Duration {
	data, err := os.ReadFile(filepath.Join(dataDir, linkedAtFile))
	if err != nil {
		return 0
	}
	linkedAt, err := time.Parse(time.RFC3339, strings.TrimSpace(string(data)))
	if err != nil {
		return 0
	}
	remaining := SyncWindowDuration - now.Sub(linkedAt)
	if remaining < 0 {
		return 0
	}
	return remaining
}
