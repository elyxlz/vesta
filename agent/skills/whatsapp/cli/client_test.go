package main

import (
	"strings"
	"testing"

	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// newLinkedTestClient builds a real (read-only) client over a temp store and stamps
// a device ID so it looks LINKED without a live pairing. Read-only keeps onConnected
// from broadcasting presence, so no path here touches the network.
func newLinkedTestClient(t *testing.T) *WhatsAppClient {
	t.Helper()
	wac, err := NewWhatsAppClient(t.TempDir(), "", "personal", true, true, map[string]bool{}, waLog.Noop)
	if err != nil {
		t.Fatalf("NewWhatsAppClient: %v", err)
	}
	t.Cleanup(wac.Disconnect)
	wac.client.Store.ID = &types.JID{User: "15551230000", Server: types.DefaultUserServer}
	return wac
}

// TestConnectRespectsPersistedPark proves the boot connect consults the PERSISTED
// park, not just Store.ID: a restart of a parked daemon must stay idle instead of
// stealing the session back and ping-ponging with the other holder.
func TestConnectRespectsPersistedPark(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.state.update(func(s *daemonState) { s.ConnParked = true })

	if err := wac.Connect(); err != nil {
		t.Fatalf("Connect returned error: %v", err)
	}
	if !wac.connModeIs(connParked) {
		t.Fatal("boot Connect must hydrate the parked posture from persisted state")
	}
	if wac.client.IsConnected() {
		t.Fatal("a parked device must stay idle at boot, not reconnect")
	}
}

// TestEnsureConnectedRefusesWhenParked pins the reconnect-refusal safety property:
// a write command's lazy reconnect must refuse while parked, or it steals the
// session back. Deleting the guard would make this reconnect (and this test fail).
func TestEnsureConnectedRefusesWhenParked(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.state.update(func(s *daemonState) { s.ConnParked = true })
	wac.setConnMode(connParked)

	err := wac.EnsureConnected()
	if err == nil || !strings.Contains(err.Error(), "parked") {
		t.Fatalf("EnsureConnected must refuse to reconnect when parked, got %v", err)
	}
}

// TestRecoverOrRestartRefusesWhenParked pins the same property on the recovery path.
// Parked, recovery must be a no-op: if the guard were removed it would drop the
// socket and hit EnsureConnected's parked refusal, whose connRecoverOnce path calls
// os.Exit and would kill this test binary. Surviving with the park intact is the proof.
func TestRecoverOrRestartRefusesWhenParked(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.state.update(func(s *daemonState) { s.ConnParked = true })
	wac.setConnMode(connParked)

	wac.recoverOrRestart("test")

	if !wac.connModeIs(connParked) {
		t.Fatal("recoverOrRestart must leave the park intact")
	}
	if err := wac.EnsureConnected(); err == nil || !strings.Contains(err.Error(), "parked") {
		t.Fatalf("still parked after recoverOrRestart; EnsureConnected should refuse, got %v", err)
	}
}

// TestDeliberateConnectClearsPark proves a deliberate connect/link (which funnels
// through onConnected on success) clears both the in-memory and the persisted park,
// so a re-link ends the parked posture and lets reconnects resume.
func TestDeliberateConnectClearsPark(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.state.update(func(s *daemonState) { s.ConnParked = true })
	wac.setConnMode(connParked)

	wac.onConnected()

	if wac.connModeIs(connParked) {
		t.Fatal("a deliberate connect must clear the in-memory park")
	}
	if wac.state.snapshot().ConnParked {
		t.Fatal("a deliberate connect must clear the persisted park")
	}
}
