package main

import (
	"errors"
	"os"
	"slices"
	"strings"
	"testing"
	"time"

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

// TestEnsureOnlineNamesThePushNameFix: a store with no push name cannot broadcast presence,
// so the account never appears online. The error must name the one command that fixes it,
// since the log line is the only place the condition ever shows.
func TestEnsureOnlineNamesThePushNameFix(t *testing.T) {
	wac, err := NewWhatsAppClient(t.TempDir(), "", "personal", false, true, map[string]bool{}, waLog.Noop)
	if err != nil {
		t.Fatalf("NewWhatsAppClient: %v", err)
	}
	t.Cleanup(wac.Disconnect)

	err = wac.EnsureOnline()
	if err == nil || !strings.Contains(err.Error(), "whatsapp profile name") {
		t.Fatalf("EnsureOnline without a push name must name `whatsapp profile name`, got %v", err)
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

// stubRecovery replaces recoverOrRestart's reconnect, sleep, and exit seams, failing
// the first failures attempts. It returns pointers to the attempt count, the sleeps
// taken, and the exit calls.
func stubRecovery(t *testing.T, failures int) (*int, *[]time.Duration, *int) {
	t.Helper()
	attempts, exits := 0, 0
	var sleeps []time.Duration
	origAttempt, origSleep, origExit := reconnectAttempt, reconnectSleep, exitProcess
	t.Cleanup(func() { reconnectAttempt, reconnectSleep, exitProcess = origAttempt, origSleep, origExit })
	reconnectAttempt = func(*WhatsAppClient) error {
		attempts++
		if attempts <= failures {
			return errors.New("dial tcp: lookup web.whatsapp.com: server misbehaving")
		}
		return nil
	}
	reconnectSleep = func(d time.Duration) { sleeps = append(sleeps, d) }
	exitProcess = func(int) { exits++ }
	return &attempts, &sleeps, &exits
}

// TestRecoverOrRestartRetriesBeforeExiting: a transient outage (e.g. DNS down for
// minutes) must be ridden out with backoff, not turned into a dead daemon.
func TestRecoverOrRestartRetriesBeforeExiting(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.notificationsDir = t.TempDir()
	attempts, sleeps, exits := stubRecovery(t, 2)

	wac.recoverOrRestart("test")

	if *attempts != 3 || *exits != 0 {
		t.Fatalf("want success on attempt 3 with no exit, got attempts=%d exits=%d", *attempts, *exits)
	}
	if want := []time.Duration{5 * time.Second, 10 * time.Second}; !slices.Equal(*sleeps, want) {
		t.Fatalf("backoff sleeps = %v, want %v", *sleeps, want)
	}
	if entries, _ := os.ReadDir(wac.notificationsDir); len(entries) != 0 {
		t.Fatalf("a recovered reconnect must not write a death marker, found %d files", len(entries))
	}
}

// TestRecoverOrRestartExitsAfterBudget: once the backoff budget is spent, recovery
// takes the existing exit path (death marker, then exit) exactly once.
func TestRecoverOrRestartExitsAfterBudget(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.notificationsDir = t.TempDir()
	attempts, sleeps, exits := stubRecovery(t, 1<<30)

	wac.recoverOrRestart("test")

	var total time.Duration
	for _, d := range *sleeps {
		if d > ReconnectBackoffMax {
			t.Fatalf("sleep %s exceeds the %s cap", d, ReconnectBackoffMax)
		}
		total += d
	}
	if total < ReconnectBudget || total > ReconnectBudget+ReconnectBackoffMax {
		t.Fatalf("total backoff %s, want about the %s budget", total, ReconnectBudget)
	}
	if *exits != 1 || *attempts != len(*sleeps)+1 {
		t.Fatalf("want one exit after %d sleeps, got exits=%d attempts=%d", len(*sleeps), *exits, *attempts)
	}
	if entries, _ := os.ReadDir(wac.notificationsDir); len(entries) != 1 {
		t.Fatalf("exhausted recovery must write one death marker, found %d files", len(entries))
	}
}

// TestRecoverOrRestartStopsWhenParkedMidRetry: the park guard is re-checked between
// attempts, so a takeover during backoff ends recovery without an exit.
func TestRecoverOrRestartStopsWhenParkedMidRetry(t *testing.T) {
	wac := newLinkedTestClient(t)
	attempts, _, exits := stubRecovery(t, 1<<30)
	reconnectAttempt = func(w *WhatsAppClient) error {
		*attempts++
		w.setConnMode(connParked)
		return errors.New("connection refused")
	}

	wac.recoverOrRestart("test")

	if *attempts != 1 || *exits != 0 {
		t.Fatalf("parked mid-retry must stop recovery, got attempts=%d exits=%d", *attempts, *exits)
	}
}
