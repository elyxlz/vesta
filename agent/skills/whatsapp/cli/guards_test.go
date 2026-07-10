package main

import (
	"strings"
	"testing"
	"time"
)

func TestGuardPairAttemptAllowsThenBlocks(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)

	if err := guardPairAttempt(dir, now, false); err != nil {
		t.Fatalf("attempt 1 should be allowed: %v", err)
	}
	if err := guardPairAttempt(dir, now.Add(time.Minute), false); err != nil {
		t.Fatalf("attempt 2 should be allowed: %v", err)
	}
	err := guardPairAttempt(dir, now.Add(2*time.Minute), false)
	if err == nil {
		t.Fatal("attempt 3 within the hour must be refused")
	}
	if !strings.Contains(err.Error(), "flagged") {
		t.Errorf("refusal must explain ban risk, got: %v", err)
	}
}

func TestGuardPairAttemptWindowExpires(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	if err := guardPairAttempt(dir, now, false); err != nil {
		t.Fatal(err)
	}
	if err := guardPairAttempt(dir, now.Add(time.Minute), false); err != nil {
		t.Fatal(err)
	}
	if err := guardPairAttempt(dir, now.Add(PairAttemptWindow+time.Minute), false); err != nil {
		t.Fatalf("attempt after the window must be allowed: %v", err)
	}
}

func TestGuardPairAttemptAcknowledgeOverrides(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	for i := 0; i < MaxPairAttempts; i++ {
		if err := guardPairAttempt(dir, now, false); err != nil {
			t.Fatal(err)
		}
	}
	if err := guardPairAttempt(dir, now, true); err != nil {
		t.Fatalf("acknowledged attempt must bypass the limit: %v", err)
	}
}

func TestSyncWindow(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	if rem := syncWindowRemaining(dir, now); rem != 0 {
		t.Fatalf("no link recorded: remaining = %v, want 0", rem)
	}
	recordLinkedAt(dir, now)
	if rem := syncWindowRemaining(dir, now.Add(time.Minute)); rem != SyncWindowDuration-time.Minute {
		t.Fatalf("remaining = %v, want %v", rem, SyncWindowDuration-time.Minute)
	}
	if rem := syncWindowRemaining(dir, now.Add(SyncWindowDuration+time.Second)); rem != 0 {
		t.Fatalf("window elapsed: remaining = %v, want 0", rem)
	}
}

// TestSyncWindowSlidesWhileActive pins the handleHistorySync composition: a
// guarded re-stamp inside the window extends it, but the same guard refuses to
// re-arm once the window has expired.
func TestSyncWindowSlidesWhileActive(t *testing.T) {
	dir := t.TempDir()
	start := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	recordLinkedAt(dir, start)

	// A batch arriving inside the window re-stamps, extending the remaining time.
	mid := start.Add(SyncWindowDuration - time.Minute)
	if syncWindowRemaining(dir, mid) <= 0 {
		t.Fatal("window should still be open mid-sync")
	}
	recordLinkedAt(dir, mid)
	if rem := syncWindowRemaining(dir, mid.Add(2*time.Minute)); rem != SyncWindowDuration-2*time.Minute {
		t.Fatalf("re-stamp did not extend the window: remaining = %v, want %v", rem, SyncWindowDuration-2*time.Minute)
	}

	// After expiry the guard condition is false, so a routine sync must not re-arm.
	expired := mid.Add(2 * time.Minute).Add(SyncWindowDuration + time.Minute)
	if syncWindowRemaining(dir, expired) > 0 {
		t.Fatal("window should be closed after expiry")
	}
	if syncWindowRemaining(dir, expired) > 0 {
		recordLinkedAt(dir, expired)
	}
	if syncWindowRemaining(dir, expired) > 0 {
		t.Fatal("expired window must not be re-armed by a guarded stamp")
	}
}
