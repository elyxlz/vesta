package main

import (
	"strings"
	"testing"
)

func TestSimpleStatusLinked(t *testing.T) {
	dir := t.TempDir()
	live := map[string]any{"logged_in": true, "connected": true, "number": "+441234567890"}
	got := simpleStatus(live, dir)
	if got["linked"] != true {
		t.Errorf("linked = %v, want true", got["linked"])
	}
	if got["connected"] != true {
		t.Errorf("connected = %v, want true", got["connected"])
	}
	if got["number"] != "+441234567890" {
		t.Errorf("number = %v, want +441234567890", got["number"])
	}
	if _, hasNext := got["next"]; hasNext {
		t.Error("a linked status must not carry a next-step hint")
	}
}

func TestSimpleStatusNotLinkedSurfacesReason(t *testing.T) {
	dir := t.TempDir()
	setExitForTest(dir, "logged_out", "unlinked from the phone (stream:error logout)")

	got := simpleStatus(map[string]any{"logged_in": false}, dir)
	if got["linked"] != false {
		t.Errorf("linked = %v, want false", got["linked"])
	}
	if got["next"] != "run: whatsapp connect --source <vesta-cloud|doubletick|self-managed>" {
		t.Errorf("next = %v, want the connect hint", got["next"])
	}
	if got["reason"] != "unlinked from the phone (stream:error logout)" {
		t.Errorf("reason = %v, want the recorded last-exit reason", got["reason"])
	}
}

// TestStatusHintSourcesAreAccepted runs every source named in the not-linked
// recovery hint through validateConnectSource, so the hint can never hand the
// agent a --source value connect rejects.
func TestStatusHintSourcesAreAccepted(t *testing.T) {
	next, ok := notLinkedStatus(t.TempDir())["next"].(string)
	if !ok {
		t.Fatal("not-linked status must carry a next hint")
	}
	start, end := strings.Index(next, "<"), strings.Index(next, ">")
	if start < 0 || end < start {
		t.Fatalf("next = %q, want a <source|...> placeholder", next)
	}
	for _, source := range strings.Split(next[start+1:end], "|") {
		if err := validateConnectSource(connectOptions{source: source}); err != nil {
			t.Errorf("hinted source %q rejected by connect: %v", source, err)
		}
	}
}

func TestSimpleStatusReportsActiveQRPairing(t *testing.T) {
	got := simpleStatus(map[string]any{
		"logged_in":   false,
		"auth_status": string(AuthStatusQRReady),
	}, t.TempDir())
	if got["connecting"] != true || got["method"] != "qr" {
		t.Fatalf("active QR status = %#v, want connecting QR", got)
	}
	next, _ := got["next"].(string)
	if strings.Contains(next, "run: whatsapp connect") || !strings.Contains(next, "do not run connect again") {
		t.Errorf("active QR next step = %q, want wait guidance without another connect", next)
	}
}

func TestSimpleStatusReportsQRServerBeforeFirstCode(t *testing.T) {
	got := simpleStatus(map[string]any{
		"logged_in": false,
		"link_port": float64(61012),
	}, t.TempDir())
	if got["connecting"] != true || got["method"] != "qr" {
		t.Fatalf("pre-QR status = %#v, want connecting QR", got)
	}
}

func TestSimpleStatusReportsPendingPhonePairing(t *testing.T) {
	got := simpleStatus(map[string]any{
		"logged_in":             false,
		"phone_pairing_pending": true,
	}, t.TempDir())
	if got["connecting"] != true || got["method"] != "phone" {
		t.Fatalf("phone pairing status = %#v, want connecting phone", got)
	}
	next, _ := got["next"].(string)
	if strings.Contains(next, "run: whatsapp connect") || !strings.Contains(next, "do not run connect again") {
		t.Errorf("phone pairing next step = %q, want wait guidance without another connect", next)
	}
}

// TestDaemonDownStatusSurfacesWhyItDied: a daemon that exited on a device conflict says so, so the
// agent reads the recorded reason instead of restarting straight back into the same conflict.
func TestDaemonDownStatusSurfacesWhyItDied(t *testing.T) {
	dir := t.TempDir()
	got := daemonDownStatus(dir)
	if got["running"] != false || got["reason"] != daemonDownMessage {
		t.Errorf("a daemon down with nothing recorded = %#v, want the plain not-running reason", got)
	}
	setExitForTest(dir, "stream_replaced", "another connection took over this device session")
	got = daemonDownStatus(dir)
	if got["reason"] != "another connection took over this device session" {
		t.Errorf("reason = %v, want the recorded last-exit reason", got["reason"])
	}
	if got["next"] != "start the daemon: whatsapp daemon start" {
		t.Errorf("next = %v, want the start hint", got["next"])
	}
}

func TestExitReasonRoundTrip(t *testing.T) {
	dir := t.TempDir()
	if loadStateFromDisk(dir).ExitReason != "" {
		t.Fatal("no exit reason yet, read must be empty")
	}
	setExitForTest(dir, "stream_replaced", "another connection took over this device session")
	st := loadStateFromDisk(dir)
	if st.ExitStatus != "stream_replaced" || st.ExitReason == "" {
		t.Errorf("exit reason round trip lost data: %+v", st)
	}
}
