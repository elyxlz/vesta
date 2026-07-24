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
	// Hourly cap: soft (override-able with --acknowledge-ban-risk) for a legitimate
	// retry a minute later. The daily/weekly caps below are HARD and structurally
	// bound the re-pair rate no acknowledgement can bypass, so nothing can burn a
	// number by re-pairing in a loop.
	MaxPairAttempts   = 2
	PairAttemptWindow = time.Hour

	MaxPairPerDay = 3
	PairDayWindow = 24 * time.Hour

	MaxPairPer7d   = 6
	PairWeekWindow = 7 * 24 * time.Hour

	// PairRetentionWindow is how long attempts are kept, so the weekly cap can see
	// them all.
	PairRetentionWindow = 7 * 24 * time.Hour

	SyncWindowDuration = 5 * time.Minute
	LinkSessionTimeout = 10 * time.Minute
)

// attemptsWithin returns the attempts that fall inside the given window ending now.
func attemptsWithin(attempts []time.Time, now time.Time, window time.Duration) []time.Time {
	var within []time.Time
	for _, attempt := range attempts {
		if now.Sub(attempt) < window {
			within = append(within, attempt)
		}
	}
	return within
}

// liveAttempts returns the attempts still inside the hourly rate-limit window.
func liveAttempts(attempts []time.Time, now time.Time) []time.Time {
	return attemptsWithin(attempts, now, PairAttemptWindow)
}

// pairAttemptsInWindow counts the live (hourly) attempts.
func pairAttemptsInWindow(attempts []time.Time, now time.Time) int {
	return len(liveAttempts(attempts, now))
}

// oldestAttempt returns the earliest attempt in a non-empty slice.
func oldestAttempt(attempts []time.Time) time.Time {
	oldest := attempts[0]
	for _, attempt := range attempts {
		if attempt.Before(oldest) {
			oldest = attempt
		}
	}
	return oldest
}

// checkPairAttempt reports whether another pairing attempt is allowed under the
// ban-avoidance rate limit, given the RAW attempt history (it filters each window
// itself) and records nothing, so callers that can fail before a code is produced
// (phone-code pairing) check first and record only on success. Caps are enforced
// widest-first: the weekly and daily caps are HARD (--acknowledge-ban-risk does
// NOT bypass them), so re-pairing cannot exceed a safe rate; only the hourly cap
// is override-able for a legitimate immediate retry.
func checkPairAttempt(attempts []time.Time, now time.Time, acknowledged bool) error {
	if weekly := attemptsWithin(attempts, now, PairWeekWindow); len(weekly) >= MaxPairPer7d {
		cooldown := (PairWeekWindow - now.Sub(oldestAttempt(weekly))).Round(time.Minute)
		return fmt.Errorf(
			"pairing blocked for %s: %d pairing attempts in the last 7 days (hard cap %d). Repeated pairing is exactly what gets WhatsApp numbers banned; this 7-day cap is NOT override-able. Wait for the oldest attempt to age out before retrying",
			cooldown, len(weekly), MaxPairPer7d)
	}
	if daily := attemptsWithin(attempts, now, PairDayWindow); len(daily) >= MaxPairPerDay {
		cooldown := (PairDayWindow - now.Sub(oldestAttempt(daily))).Round(time.Minute)
		return fmt.Errorf(
			"pairing blocked for %s: %d pairing attempts in the last 24 hours (hard cap %d). Repeated pairing gets WhatsApp numbers banned; this daily cap is NOT override-able. Wait out the cooldown before retrying",
			cooldown, len(daily), MaxPairPerDay)
	}
	if hourly := attemptsWithin(attempts, now, PairAttemptWindow); len(hourly) >= MaxPairAttempts && !acknowledged {
		cooldown := (PairAttemptWindow - now.Sub(oldestAttempt(hourly))).Round(time.Minute)
		return fmt.Errorf(
			"pairing blocked for %s: %d pairing attempts in the last hour. Repeated pairing attempts get WhatsApp numbers flagged and banned. Wait out the cooldown and only retry with the user's explicit go-ahead. A self-hosted link can pass --acknowledge-ban-risk to override; a managed number has no override and must wait out the cooldown",
			cooldown, len(hourly))
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
