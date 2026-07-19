package main

import (
	"errors"
	"strings"
	"testing"
	"time"
)

// TestChooseLinkerParadigm pins the one construction-time decision: a box that can
// reach a pool (a direct key, or the vesta.run identity path on a genuine cloud
// tenant) gets the managed linker; a plain box (including a self-hosted CONTAINER,
// whose identity env is present but which is not a paid tenant) gets the QR linker.
func TestChooseLinkerParadigm(t *testing.T) {
	cases := []struct {
		name string
		cfg  managedConfig
		want string
	}{
		{"direct key", managedConfig{directURL: "https://box", directKey: "wak_x"}, "managed"},
		{"cloud tenant", managedConfig{vestadBase: "https://localhost:1", agentName: "a", agentToken: "t", cloudManaged: true}, "managed"},
		{"self-hosted container (identity but not a tenant)", managedConfig{vestadBase: "https://localhost:1", agentName: "a", agentToken: "t"}, "self-hosted"},
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
	up := func() bool { return true }
	guarded := l.guardedPairPhone(up, func(string) (string, error) { called = true; return "C0DE", nil })
	if _, err := guarded("+447700900000"); !errors.Is(err, errRateLimited) {
		t.Fatalf("guarded pair at cap = %v, want errRateLimited", err)
	}
	if called {
		t.Fatal("PairPhone must not be called once the rate-limit cap is reached")
	}
}

// TestGuardedPairPhoneRecordsOnDispatch proves the guard records an attempt the
// moment the request is dispatched to WhatsApp (socket up), NOT only on success: a
// request that reaches WhatsApp but errors mid-handshake must still burn a slot, or a
// retry loop would slip past the cap.
func TestGuardedPairPhoneRecordsOnDispatch(t *testing.T) {
	store := newStateStore(t.TempDir())
	l := &managedLinker{state: store}
	up := func() bool { return true }
	guarded := l.guardedPairPhone(up, func(string) (string, error) { return "", errors.New("handshake failed after dispatch") })
	if _, err := guarded("+447700900000"); err == nil {
		t.Fatal("expected the underlying pair failure to surface")
	}
	if n := len(store.snapshot().PairAttempts); n != 1 {
		t.Fatalf("a dispatched request must record one attempt even on a response error, got %d", n)
	}
}

// TestGuardedPairPhoneNoRecordWhenNotConnected proves a pre-dispatch failure (socket
// not up yet) burns no slot and never calls pair, so a transient failure never eats
// into the cap.
func TestGuardedPairPhoneNoRecordWhenNotConnected(t *testing.T) {
	store := newStateStore(t.TempDir())
	l := &managedLinker{state: store}
	called := false
	down := func() bool { return false }
	guarded := l.guardedPairPhone(down, func(string) (string, error) { called = true; return "C0DE", nil })
	if _, err := guarded("+447700900000"); err == nil {
		t.Fatal("expected a not-connected error before dispatch")
	}
	if called {
		t.Fatal("pair must not be called when the socket is not up")
	}
	if n := len(store.snapshot().PairAttempts); n != 0 {
		t.Fatalf("a pre-dispatch failure must record nothing, got %d attempts", n)
	}
}
