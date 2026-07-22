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

// TestWeeklyCapNotOverridable proves the 7-day hard cap blocks even with
// --acknowledge-ban-risk: nothing can re-pair a number past the weekly budget.
func TestWeeklyCapNotOverridable(t *testing.T) {
	base := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	// MaxPairPer7d attempts spread over the week (each > 24h apart so the daily cap
	// does not trip first), all inside PairWeekWindow.
	var attempts []time.Time
	for i := 0; i < MaxPairPer7d; i++ {
		attempts = append(attempts, base.Add(time.Duration(i)*26*time.Hour))
	}
	now := base.Add(time.Duration(MaxPairPer7d) * 26 * time.Hour) // still < 7d from base
	err := checkPairAttempt(attempts, now, true)
	if err == nil {
		t.Fatal("weekly cap must block even when acknowledged")
	}
	if !strings.Contains(err.Error(), "7 days") {
		t.Errorf("weekly refusal must cite the 7-day cap, got: %v", err)
	}
}

// TestDailyCapNotOverridable proves the 24h hard cap blocks even with
// --acknowledge-ban-risk, while staying under the weekly cap.
func TestDailyCapNotOverridable(t *testing.T) {
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	var attempts []time.Time
	for i := 0; i < MaxPairPerDay; i++ {
		attempts = append(attempts, now.Add(-time.Duration(i+1)*time.Hour))
	}
	err := checkPairAttempt(attempts, now, true)
	if err == nil {
		t.Fatal("daily cap must block even when acknowledged")
	}
	if !strings.Contains(err.Error(), "24 hours") {
		t.Errorf("daily refusal must cite the 24-hour cap, got: %v", err)
	}
}

// TestHourlyCapOverridable proves the hourly cap blocks unacknowledged but is
// bypassed by --acknowledge-ban-risk when under the daily and weekly caps.
func TestHourlyCapOverridable(t *testing.T) {
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	attempts := []time.Time{now.Add(-2 * time.Minute), now.Add(-time.Minute)}
	if err := checkPairAttempt(attempts, now, false); err == nil {
		t.Fatal("hourly cap must block an unacknowledged attempt")
	}
	if err := checkPairAttempt(attempts, now, true); err != nil {
		t.Fatalf("hourly cap must be override-able when under daily/weekly: %v", err)
	}
}

// TestPairAttemptsOutsideWindowIgnored proves attempts older than the widest
// window do not count toward any cap.
func TestPairAttemptsOutsideWindowIgnored(t *testing.T) {
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	var attempts []time.Time
	for i := 0; i < MaxPairPer7d+3; i++ {
		attempts = append(attempts, now.Add(-PairWeekWindow-time.Duration(i+1)*time.Hour))
	}
	if err := checkPairAttempt(attempts, now, false); err != nil {
		t.Fatalf("aged-out attempts must not count: %v", err)
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
