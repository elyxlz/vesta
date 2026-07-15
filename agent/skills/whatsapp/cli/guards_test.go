package main

import (
	"strings"
	"testing"
	"time"
)

// TestTryRecordPairAttemptAllowsThenBlocks drives the store's atomic
// check-and-record: two attempts pass, the third within the hour is refused.
func TestTryRecordPairAttemptAllowsThenBlocks(t *testing.T) {
	s := newStateStore(t.TempDir())
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)

	if err := s.tryRecordPairAttempt(now, false); err != nil {
		t.Fatalf("attempt 1 should be allowed: %v", err)
	}
	if err := s.tryRecordPairAttempt(now.Add(time.Minute), false); err != nil {
		t.Fatalf("attempt 2 should be allowed: %v", err)
	}
	err := s.tryRecordPairAttempt(now.Add(2*time.Minute), false)
	if err == nil {
		t.Fatal("attempt 3 within the hour must be refused")
	}
	if !strings.Contains(err.Error(), "flagged") {
		t.Errorf("refusal must explain ban risk, got: %v", err)
	}
}

// TestCheckPairAttemptDoesNotRecord proves a failed phone-code pairing (check
// only, no code produced) never consumes a slot.
func TestCheckPairAttemptDoesNotRecord(t *testing.T) {
	s := newStateStore(t.TempDir())
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)

	for i := 0; i < 10; i++ {
		when := now.Add(time.Duration(i) * time.Second)
		if err := checkPairAttempt(liveAttempts(s.snapshot().PairAttempts, when), when, false); err != nil {
			t.Fatalf("check %d must stay allowed when nothing is recorded: %v", i, err)
		}
	}
	if n := pairAttemptsInWindow(s.snapshot().PairAttempts, now); n != 0 {
		t.Fatalf("checks must not record; want 0 attempts, got %d", n)
	}
}

// TestRecordPairAttemptThenCheckBlocks proves only recorded code generations
// count toward the limit.
func TestRecordPairAttemptThenCheckBlocks(t *testing.T) {
	s := newStateStore(t.TempDir())
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)

	for i := 0; i < MaxPairAttempts; i++ {
		if err := checkPairAttempt(liveAttempts(s.snapshot().PairAttempts, now), now, false); err != nil {
			t.Fatalf("check %d before recording must pass: %v", i, err)
		}
		s.recordPairAttempt(now)
	}
	if err := checkPairAttempt(liveAttempts(s.snapshot().PairAttempts, now), now, false); err == nil {
		t.Fatal("check must be refused once MaxPairAttempts codes are recorded")
	}
}

// TestPairAttemptWindowExpires proves attempts age out of the window.
func TestPairAttemptWindowExpires(t *testing.T) {
	s := newStateStore(t.TempDir())
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	if err := s.tryRecordPairAttempt(now, false); err != nil {
		t.Fatal(err)
	}
	if err := s.tryRecordPairAttempt(now.Add(time.Minute), false); err != nil {
		t.Fatal(err)
	}
	if err := s.tryRecordPairAttempt(now.Add(PairAttemptWindow+time.Minute), false); err != nil {
		t.Fatalf("attempt after the window must be allowed: %v", err)
	}
}

// TestPairAttemptAcknowledgeOverrides proves --acknowledge-ban-risk bypasses the limit.
func TestPairAttemptAcknowledgeOverrides(t *testing.T) {
	s := newStateStore(t.TempDir())
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	for i := 0; i < MaxPairAttempts; i++ {
		if err := s.tryRecordPairAttempt(now, false); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.tryRecordPairAttempt(now, true); err != nil {
		t.Fatalf("acknowledged attempt must bypass the limit: %v", err)
	}
}

func TestSyncWindow(t *testing.T) {
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	if rem := syncWindowRemaining(time.Time{}, now); rem != 0 {
		t.Fatalf("no link recorded: remaining = %v, want 0", rem)
	}
	if rem := syncWindowRemaining(now, now.Add(time.Minute)); rem != SyncWindowDuration-time.Minute {
		t.Fatalf("remaining = %v, want %v", rem, SyncWindowDuration-time.Minute)
	}
	if rem := syncWindowRemaining(now, now.Add(SyncWindowDuration+time.Second)); rem != 0 {
		t.Fatalf("window elapsed: remaining = %v, want 0", rem)
	}
}

// TestSyncWindowSlidesWhileActive pins the handleHistorySync composition: a
// re-stamp inside the window extends it, but a stamp is refused once expired.
func TestSyncWindowSlidesWhileActive(t *testing.T) {
	start := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)

	// A batch arriving inside the window re-stamps, extending the remaining time.
	mid := start.Add(SyncWindowDuration - time.Minute)
	if syncWindowRemaining(start, mid) <= 0 {
		t.Fatal("window should still be open mid-sync")
	}
	// After a re-stamp at mid, the window runs SyncWindowDuration from mid.
	if rem := syncWindowRemaining(mid, mid.Add(2*time.Minute)); rem != SyncWindowDuration-2*time.Minute {
		t.Fatalf("re-stamp did not extend the window: remaining = %v, want %v", rem, SyncWindowDuration-2*time.Minute)
	}

	// After expiry the guard condition is false, so a routine sync must not re-arm.
	expired := start.Add(SyncWindowDuration + time.Minute)
	if syncWindowRemaining(start, expired) > 0 {
		t.Fatal("window should be closed after expiry")
	}
}
