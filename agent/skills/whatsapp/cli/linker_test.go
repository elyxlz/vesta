package main

import (
	"errors"
	"strings"
	"testing"
	"time"
)

// TestChooseLinkerParadigm pins the one construction-time decision: a box that can
// reach a pool (direct key or the vesta.run identity path) gets the managed linker;
// a plain box gets the QR linker.
func TestChooseLinkerParadigm(t *testing.T) {
	cases := []struct {
		name string
		cfg  managedConfig
		want string
	}{
		{"direct key", managedConfig{directURL: "https://box", directKey: "wak_x"}, "managed"},
		{"vesta.run identity", managedConfig{vestadBase: "https://localhost:1", agentName: "a", agentToken: "t"}, "managed"},
		{"plain box", managedConfig{}, "self-hosted"},
	}
	for _, tc := range cases {
		l := chooseLinker(tc.cfg, newStateStore(t.TempDir()))
		if l.name() != tc.want {
			t.Errorf("%s: chose %q, want %q", tc.name, l.name(), tc.want)
		}
	}
}

// TestWrongParadigmRejected proves each linker rejects the other paradigm's
// commands, so the mode decision lives in the constructed value, not inline checks.
func TestWrongParadigmRejected(t *testing.T) {
	qr := qrLinker{}
	if _, err := qr.provision(nil); err == nil || !strings.Contains(err.Error(), "whatsapp connect") {
		t.Errorf("qr linker must reject provision, got %v", err)
	}

	managed := &managedLinker{}
	if _, err := managed.linkQR(nil, 0); err == nil || !strings.Contains(err.Error(), "whatsapp connect") {
		t.Errorf("managed linker must reject linkQR, got %v", err)
	}
	if _, err := managed.pairCode(nil, "+1"); err == nil || !strings.Contains(err.Error(), "whatsapp connect") {
		t.Errorf("managed linker must reject pairCode, got %v", err)
	}
}

// TestChooseLinkerPersistsDirectCredsAcrossEnvScrub proves the direct-mode pool
// creds survive an env scrub: env creds are persisted into state, and a later run
// with an empty env recovers them (and still selects the managed linker).
func TestChooseLinkerPersistsDirectCredsAcrossEnvScrub(t *testing.T) {
	dir := t.TempDir()

	// First run: creds come from the environment (via cfg) and get persisted.
	if l := chooseLinker(managedConfig{directURL: "https://wa.example", directKey: "wak_abc"}, newStateStore(dir)); l.name() != "managed" {
		t.Fatalf("env creds should select managed, got %q", l.name())
	}
	if st := loadStateFromDisk(dir); st.DirectURL != "https://wa.example" || st.DirectKey != "wak_abc" {
		t.Fatalf("direct creds not persisted: %+v", st)
	}

	// Later run with a scrubbed environment: creds load from state, still managed.
	if l := chooseLinker(managedConfig{}, newStateStore(dir)); l.name() != "managed" {
		t.Fatalf("creds not recovered from state after env scrub: got %q", l.name())
	}
}

// TestChooseLinkerKeepsNumberWhenReconcilingCreds proves persisting direct creds
// does not clobber an already-saved number in the consolidated state.
func TestChooseLinkerKeepsNumberWhenReconcilingCreds(t *testing.T) {
	dir := t.TempDir()
	newStateStore(dir).update(func(s *daemonState) { s.MSISDN = "+447700900009" })
	chooseLinker(managedConfig{directURL: "https://wa.example", directKey: "wak_abc"}, newStateStore(dir))
	if st := loadStateFromDisk(dir); st.MSISDN != "+447700900009" || st.DirectKey != "wak_abc" {
		t.Fatalf("reconcile clobbered number or creds: %+v", st)
	}
}

// TestGuardedPairPhoneBlocksAtCap proves the managed path is gated by the same
// ban-avoidance rate-limit guard as the phone path: once the cap is reached the
// guard returns errRateLimited and PairPhone is never called (no real pairing
// request from a datacenter IP on a minutes-old number).
func TestGuardedPairPhoneBlocksAtCap(t *testing.T) {
	store := newStateStore(t.TempDir())
	now := time.Now()
	store.update(func(s *daemonState) {
		for i := 0; i < MaxPairAttempts; i++ {
			s.PairAttempts = append(s.PairAttempts, now)
		}
	})
	l := &managedLinker{state: store}
	called := false
	guarded := l.guardedPairPhone(func(string) (string, error) { called = true; return "C0DE", nil })
	if _, err := guarded("+447700900000"); !errors.Is(err, errRateLimited) {
		t.Fatalf("guarded pair at cap = %v, want errRateLimited", err)
	}
	if called {
		t.Fatal("PairPhone must not be called once the rate-limit cap is reached")
	}
}

// TestGuardedPairPhoneRecordsOnGeneratedCode proves the guard records an attempt
// only when a code is actually minted (so the cap actually advances on the managed
// path, matching the phone path's checkPairAttempt-then-record contract).
func TestGuardedPairPhoneRecordsOnGeneratedCode(t *testing.T) {
	store := newStateStore(t.TempDir())
	l := &managedLinker{state: store}
	guarded := l.guardedPairPhone(func(string) (string, error) { return "C0DE", nil })
	if _, err := guarded("+447700900000"); err != nil {
		t.Fatalf("guarded pair below cap: %v", err)
	}
	if n := len(store.snapshot().PairAttempts); n != 1 {
		t.Fatalf("a generated code must record exactly one attempt, got %d", n)
	}
}

// TestGuardedPairPhoneNoRecordOnFailure proves a pre-code failure (e.g. websocket
// not up yet) burns no slot, so a transient failure never eats into the cap.
func TestGuardedPairPhoneNoRecordOnFailure(t *testing.T) {
	store := newStateStore(t.TempDir())
	l := &managedLinker{state: store}
	guarded := l.guardedPairPhone(func(string) (string, error) { return "", errors.New("websocket not up") })
	if _, err := guarded("+447700900000"); err == nil {
		t.Fatal("expected the underlying pair failure to surface")
	}
	if n := len(store.snapshot().PairAttempts); n != 0 {
		t.Fatalf("a pre-code failure must record nothing, got %d attempts", n)
	}
}
