package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The hold exists for an account the provider has flagged, so the property under test is that
// NOTHING brings the daemon up while it is set. The start on either side of the hold is the
// control: without it a refusal proves only that this test environment cannot start a daemon.
func TestAHoldRefusesEveryBringupAndReleaseRestoresIt(t *testing.T) {
	hermeticHome(t, modeServe)

	if _, err := startDaemonProcess(nil); err != nil {
		t.Fatalf("the environment must be able to start a daemon before a hold means anything: %v", err)
	}
	if _, err := stopDaemon(); err != nil {
		t.Fatalf("stop failed: %v", err)
	}

	if err := writeHold("under provider review"); err != nil {
		t.Fatalf("writeHold failed: %v", err)
	}
	if _, err := startDaemonProcess(nil); err == nil {
		t.Error("an explicit start brought the daemon up while held")
	}
	// The implicit bringup every agent-facing command runs is the path that actually caused the
	// problem: a read-only query spawning a serve nobody asked for.
	if err := ensureDaemon(); err == nil {
		t.Error("the implicit bringup ignored the hold")
	}
	if daemonAlive(getSocketPath()) {
		t.Error("a held instance answered on its socket")
	}
	if _, err := os.Stat(daemonPidfile()); !os.IsNotExist(err) {
		t.Errorf("a refused start must leave no pid record, got %v", err)
	}

	if err := clearHold(); err != nil {
		t.Fatalf("clearHold failed: %v", err)
	}
	if _, err := startDaemonProcess(nil); err != nil {
		t.Fatalf("a released instance must start again: %v", err)
	}
	if _, err := stopDaemon(); err != nil {
		t.Fatalf("stop failed: %v", err)
	}
}

// The refusal has to say why, or an operator meeting it months later reads it as a broken daemon
// and starts debugging the wrong thing.
func TestTheRefusalCarriesTheReason(t *testing.T) {
	hermeticHome(t, modeMute)
	if err := writeHold("number flagged 8 Jul"); err != nil {
		t.Fatalf("writeHold failed: %v", err)
	}
	_, err := startDaemonProcess(nil)
	if err == nil {
		t.Fatal("a held start must fail")
	}
	if !strings.Contains(err.Error(), "number flagged 8 Jul") {
		t.Errorf("the refusal dropped the reason: %q", err)
	}
	if !strings.Contains(err.Error(), "unhold") {
		t.Errorf("the refusal must name the way out: %q", err)
	}

	// A hold with no reason still holds, and still points at the file rather than leaving the
	// operator to guess where the state lives.
	if err := writeHold(""); err != nil {
		t.Fatalf("writeHold failed: %v", err)
	}
	if _, err = startDaemonProcess(nil); err == nil {
		t.Fatal("a reasonless hold must still hold")
	}
	if !strings.Contains(err.Error(), holdFile()) {
		t.Errorf("a reasonless refusal must name the hold file: %q", err)
	}
}

// Two instances are two accounts, so holding a flagged one must not take down a healthy one.
func TestAHoldIsPerInstance(t *testing.T) {
	home := hermeticHome(t, modeMute, "--instance", "personal")
	if err := writeHold("flagged"); err != nil {
		t.Fatalf("writeHold failed: %v", err)
	}
	held := holdFile()
	if !strings.Contains(held, "personal") {
		t.Fatalf("the named instance wrote to the default instance's path: %s", held)
	}

	withArgs(t)
	if _, isHeld := heldReason(); isHeld {
		t.Error("holding a named instance also held the default one")
	}
	if _, err := os.Stat(filepath.Join(home, ".whatsapp", "hold")); !os.IsNotExist(err) {
		t.Errorf("the default instance must have no hold file, got %v", err)
	}
}

// Releasing starts nothing: whether a flagged account should reconnect at all is a decision the
// operator makes next, not a side effect of clearing the flag.
func TestReleasingAHoldStartsNothing(t *testing.T) {
	hermeticHome(t, modeServe)
	if err := writeHold("flagged"); err != nil {
		t.Fatalf("writeHold failed: %v", err)
	}
	if err := clearHold(); err != nil {
		t.Fatalf("clearHold failed: %v", err)
	}
	if daemonAlive(getSocketPath()) {
		t.Error("releasing the hold brought the daemon up by itself")
	}
	if err := clearHold(); err != nil {
		t.Errorf("releasing an instance that is not held must be a no-op, got %v", err)
	}
}
