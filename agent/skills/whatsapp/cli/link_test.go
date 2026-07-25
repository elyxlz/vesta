package main

import (
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"sync/atomic"
	"testing"
	"time"
)

func TestLinkServeArgs(t *testing.T) {
	savedArgs := os.Args
	defer func() { os.Args = savedArgs }()

	cases := []struct {
		name string
		args []string
		want []string
	}{
		{"no instance flag", []string{"whatsapp", "link"}, nil},
		{"instance flag", []string{"whatsapp", "link", "--instance", "personal"}, []string{"--instance", "personal"}},
		{"instance flag with =", []string{"whatsapp", "link", "--instance=personal"}, []string{"--instance", "personal"}},
	}
	for _, tc := range cases {
		os.Args = tc.args
		if got := linkServeArgs(); !reflect.DeepEqual(got, tc.want) {
			t.Errorf("%s: linkServeArgs() = %#v, want %#v", tc.name, got, tc.want)
		}
	}
}

func TestLinkPageURL(t *testing.T) {
	cases := []struct {
		tunnel, agent, service string
		port                   int
		want                   string
	}{
		{"https://foo.vesta.run", "gianfranco", "wa-link", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link/"},
		{"https://foo.vesta.run/", "gianfranco", "wa-link", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link/"},
		{"https://foo.vesta.run", "gianfranco", "wa-link-personal", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link-personal/"},
		{"", "gianfranco", "wa-link", 8811, "http://localhost:8811/"},
		{"", "", "wa-link", 8811, "http://localhost:8811/"},
	}
	for _, tc := range cases {
		if got := linkPageURL(tc.tunnel, tc.agent, tc.service, tc.port); got != tc.want {
			t.Errorf("linkPageURL(%q,%q,%q,%d) = %q, want %q", tc.tunnel, tc.agent, tc.service, tc.port, got, tc.want)
		}
	}
}

func TestParsePortFlag(t *testing.T) {
	cases := []struct {
		value   string
		want    int
		wantErr bool
	}{
		{"", 0, false},
		{"8080", 8080, false},
		{"65535", 65535, false},
		{"0", 0, false},
		{"bad", 0, true},
		{"65536", 0, true},
		{"-1", 0, true},
	}
	for _, tc := range cases {
		got, err := parsePortFlag(tc.value)
		if (err != nil) != tc.wantErr {
			t.Errorf("parsePortFlag(%q) error = %v, wantErr %v", tc.value, err, tc.wantErr)
		}
		if err == nil && got != tc.want {
			t.Errorf("parsePortFlag(%q) = %d, want %d", tc.value, got, tc.want)
		}
	}
}

func TestWaitForQRReadyReturnsWhenPageIsLive(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	port := server.Listener.Addr().(*net.TCPAddr).Port

	savedPoll, savedTimeout := linkReadyPoll, linkReadyTimeout
	linkReadyPoll, linkReadyTimeout = time.Millisecond, time.Second
	defer func() {
		linkReadyPoll, linkReadyTimeout = savedPoll, savedTimeout
	}()

	result := make(chan socketCommandResult)
	if terminal, ready := waitForQRReady(port, result); !ready || terminal.exitCode != 0 {
		t.Fatalf("waitForQRReady = (%+v, %v), want ready", terminal, ready)
	}
}

func TestWaitForQRReadyReturnsImmediatePairingError(t *testing.T) {
	result := make(chan socketCommandResult, 1)
	result <- socketCommandResult{output: []byte(`{"error":"pairing already in progress"}`), exitCode: 1, connected: true}

	terminal, ready := waitForQRReady(1, result)
	if ready || terminal.exitCode != 1 {
		t.Fatalf("waitForQRReady = (%+v, %v), want terminal error", terminal, ready)
	}
}

func TestConnectLockSerializesConcurrentPairingSetup(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	first, err := acquireConnectLock()
	if err != nil {
		t.Fatal(err)
	}
	var secondAcquired atomic.Bool
	done := make(chan struct{})
	go func() {
		second, lockErr := acquireConnectLock()
		if lockErr == nil {
			secondAcquired.Store(true)
			releaseConnectLock(second)
		}
		close(done)
	}()

	time.Sleep(50 * time.Millisecond)
	if secondAcquired.Load() {
		t.Fatal("a concurrent connect entered before the first released its setup lock")
	}
	releaseConnectLock(first)
	select {
	case <-done:
		if !secondAcquired.Load() {
			t.Fatal("the second connect never acquired the released setup lock")
		}
	case <-time.After(time.Second):
		t.Fatal("the second connect stayed blocked after the first released its lock")
	}
}

func TestPairingCleanupRunsBeforeTheNextPairingCanReuseThePort(t *testing.T) {
	var events []string
	finishPairing(
		func() { events = append(events, "cleanup-old-registration") },
		func() { events = append(events, "release-pairing-lock") },
	)
	if !reflect.DeepEqual(events, []string{"cleanup-old-registration", "release-pairing-lock"}) {
		t.Fatalf("finishPairing order = %v", events)
	}
}

func TestRejectedPairingCleansOnlyItsOwnUnusedRegistration(t *testing.T) {
	cleanups := 0
	cleanup := func() { cleanups++ }
	cleanupRejectedPairing(cleanup, 0, 61012)
	if cleanups != 1 {
		t.Fatalf("unused rejected registration cleanup count = %d, want 1", cleanups)
	}
	cleanupRejectedPairing(cleanup, 61013, 61013)
	if cleanups != 1 {
		t.Fatalf("active QR registration was cleaned up; count = %d", cleanups)
	}
}

func TestPhonePairingPendingBlocksAnotherPairingUntilCleared(t *testing.T) {
	wac := &WhatsAppClient{}
	now := time.Now()
	release, ok := wac.beginPairing()
	if !ok {
		t.Fatal("initial phone pairing could not start")
	}
	wac.markPhonePairingPending(now)
	release()
	if !wac.phonePairingPending(now.Add(time.Second)) {
		t.Fatal("fresh phone pairing was not reported pending")
	}
	if release, ok := wac.beginPairing(); ok {
		release()
		t.Fatal("another pairing entered while the phone code was pending")
	}
	if !wac.connModeIs(connPairing) {
		t.Fatal("phone pairing window did not keep connection recovery paused")
	}
	wac.clearPhonePairingPending()
	if !wac.connModeIs(connNormal) {
		t.Fatal("clearing phone pairing did not restore normal connection mode")
	}
	release, ok = wac.beginPairing()
	if !ok {
		t.Fatal("pairing stayed blocked after the phone pairing cleared")
	}
	release()
}

func TestPhonePairingStatusExpiresTheRecoveryPosture(t *testing.T) {
	wac := &WhatsAppClient{}
	wac.setConnMode(connPairing)
	wac.authMutex.Lock()
	wac.phonePairUntil = time.Now().Add(-time.Second)
	wac.authMutex.Unlock()

	if seconds := wac.phonePairingSecondsLeft(time.Now()); seconds != 0 {
		t.Fatalf("expired phone pairing seconds = %d, want 0", seconds)
	}
	if !wac.connModeIs(connNormal) {
		t.Fatal("expired phone pairing left connection recovery paused")
	}
	if wac.phonePairingPending(time.Now()) {
		t.Fatal("expired phone pairing stayed pending")
	}
}
