package main

import "testing"

// TestDaemonLockRejectsSecondDaemon is the device-session conflict fix: once one
// daemon holds the lock, a second acquire on the same data dir is refused
// (EWOULDBLOCK surfaces as ok=false), so two daemons can never connect with the
// same device identity.
func TestDaemonLockRejectsSecondDaemon(t *testing.T) {
	dir := t.TempDir()

	first, ok, err := acquireDaemonLock(dir)
	if err != nil {
		t.Fatalf("first acquire errored: %v", err)
	}
	if !ok {
		t.Fatal("first daemon must get the lock")
	}
	defer first.Close()

	second, ok, err := acquireDaemonLock(dir)
	if err != nil {
		t.Fatalf("second acquire errored: %v", err)
	}
	if ok {
		t.Fatal("second daemon must be rejected while the first holds the lock")
		second.Close()
	}
}

// TestDaemonLockReacquiredAfterRelease proves the lock is not permanent: once the
// holder closes it, a new daemon can take it (a clean restart succeeds).
func TestDaemonLockReacquiredAfterRelease(t *testing.T) {
	dir := t.TempDir()

	first, ok, err := acquireDaemonLock(dir)
	if err != nil || !ok {
		t.Fatalf("first acquire failed: ok=%v err=%v", ok, err)
	}
	first.Close()

	second, ok, err := acquireDaemonLock(dir)
	if err != nil || !ok {
		t.Fatalf("re-acquire after release failed: ok=%v err=%v", ok, err)
	}
	second.Close()
}
