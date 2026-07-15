package main

import (
	"strings"
	"testing"
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
	if _, err := qr.provision(nil); err == nil || !strings.Contains(err.Error(), "whatsapp link") {
		t.Errorf("qr linker must reject provision, got %v", err)
	}

	managed := &managedLinker{}
	if _, err := managed.linkQR(nil, 0); err == nil || !strings.Contains(err.Error(), "whatsapp provision") {
		t.Errorf("managed linker must reject linkQR, got %v", err)
	}
	if _, err := managed.pairCode(nil, "+1"); err == nil || !strings.Contains(err.Error(), "whatsapp provision") {
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
