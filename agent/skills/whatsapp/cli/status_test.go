package main

import "testing"

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
	if got["next"] != "run: whatsapp connect" {
		t.Errorf("next = %v, want the connect hint", got["next"])
	}
	if got["reason"] != "unlinked from the phone (stream:error logout)" {
		t.Errorf("reason = %v, want the recorded last-exit reason", got["reason"])
	}
}

func TestNotLinkedStatusFallsBackToStartError(t *testing.T) {
	dir := t.TempDir()
	got := notLinkedStatus(dir, "daemon did not answer")
	if got["reason"] != "daemon did not answer" {
		t.Errorf("reason = %v, want the start error when no last-exit exists", got["reason"])
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
