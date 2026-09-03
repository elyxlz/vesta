package main

import (
	"os/exec"
	"strings"
	"testing"
)

// WHISPER_LANGUAGE rides into `transcribe` as --language, so the provider and
// the whisper fallback both honor the pin; unset, the command auto-detects.
func TestTranscribeArgsCarryTheLanguagePin(t *testing.T) {
	if got := strings.Join(transcribeArgs("/tmp/a.ogg", ""), " "); got != "/tmp/a.ogg" {
		t.Errorf("no pin: args = %q, want the file alone", got)
	}
	if got := strings.Join(transcribeArgs("/tmp/a.ogg", "it"), " "); got != "/tmp/a.ogg --language it" {
		t.Errorf("pinned: args = %q, want --language it", got)
	}
}

// transcribeError names why `transcribe` did not answer: the {error} it
// printed, a missing command (with the install line), or a bare exit failure,
// so the notification the agent reads says what to fix.
func TestTranscribeError(t *testing.T) {
	exit := &exec.ExitError{}
	notFound := &exec.Error{Name: "transcribe", Err: exec.ErrNotFound}

	if err := transcribeError([]byte(`{"error":"STT not configured; whisper: whisper-cli not found"}`), exit); err == nil ||
		!strings.Contains(err.Error(), "whisper-cli not found") {
		t.Errorf("structured error = %v, want it to carry the stderr reason", err)
	}
	if err := transcribeError(nil, notFound); err == nil || !strings.Contains(err.Error(), "uv tool install") {
		t.Errorf("missing-command error = %v, want the install line", err)
	}
	if err := transcribeError([]byte("not json"), exit); err == nil {
		t.Errorf("bare failure error = nil, want a non-nil error")
	}
}
