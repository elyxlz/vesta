package main

import (
	"errors"
	"os/exec"
	"strings"
	"testing"
)

// The thread budget uses every core on a small box and stays at
// WhisperMaxThreads on a big one, so one transcription never pins a large
// host while a single-core box still gets a worker.
func TestWhisperThreadsClampsToMaxOnBigBoxes(t *testing.T) {
	cases := []struct {
		numCPU int
		want   uint
	}{
		{numCPU: 1, want: 1},
		{numCPU: 2, want: 2},
		{numCPU: 4, want: 4},
		{numCPU: 8, want: 4},
		{numCPU: 32, want: 4},
	}
	for _, tc := range cases {
		if got := whisperThreads(tc.numCPU); got != tc.want {
			t.Errorf("whisperThreads(%d) = %d, want %d", tc.numCPU, got, tc.want)
		}
	}
}

// whisper.cpp emits bracketed silence/tags like "[Musica]", "[BLANK_AUDIO]",
// "[Musik]", "[tk]" instead of erroring on near-silent clips; those must be
// treated as junk (silence) so we never deliver the tag as a transcript, while
// a real transcript that merely contains a bracketed word must NOT be dropped.
// The regex anchors to the whole string, which is what makes the distinction.
func TestWhisperOutputJunk(t *testing.T) {
	junk := []string{
		"",
		"   ",
		"\t\n",
		"[Musica]",
		"[BLANK_AUDIO]",
		"[Musik]",
		"[tk]",
		"[Musica]  ", // trailing whitespace still tag-only
	}
	for _, in := range junk {
		if !whisperOutputJunk(in) {
			t.Errorf("whisperOutputJunk(%q) = false, want true", in)
		}
	}
	real := []string{
		"Ciao, come stai?",
		"See you at [the pub] later",   // bracketed word inside a real transcript
		"[Musica] and then he said go", // tag plus real content
		"uh [tk] hmm actually no",
		"x",
	}
	for _, in := range real {
		if whisperOutputJunk(in) {
			t.Errorf("whisperOutputJunk(%q) = true, want false", in)
		}
	}
}

// transcriptDecision keeps voice STT primary and whisper the fallback: a clean
// STT answer (voiceErr == nil) always wins, even an empty one (genuine silence);
// otherwise whisper is used, its error propagates, and a junk (silence-tag)
// whisper result is dropped to empty rather than delivered.
func TestTranscriptDecision(t *testing.T) {
	whisperFail := errors.New("whisper boom")
	voiceFail := errors.New("voice unavailable")
	cases := []struct {
		name        string
		voiceText   string
		voiceErr    error
		whisperText string
		whisperErr  error
		wantText    string
		wantErr     bool
	}{
		{name: "stt wins", voiceText: "ciao", voiceErr: nil, whisperText: "whatever", wantText: "ciao"},
		{name: "stt empty is authoritative", voiceText: "", voiceErr: nil, whisperText: "[Musica]", wantText: ""},
		{name: "fallback to whisper", voiceErr: voiceFail, whisperText: "hello there", wantText: "hello there"},
		{name: "whisper junk dropped", voiceErr: voiceFail, whisperText: "[Musica]", wantText: ""},
		{name: "both fail", voiceErr: voiceFail, whisperErr: whisperFail, wantErr: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := transcriptDecision(tc.voiceText, tc.voiceErr, tc.whisperText, tc.whisperErr)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("transcriptDecision(%q) err = nil, want error", tc.name)
				}
				return
			}
			if err != nil {
				t.Fatalf("transcriptDecision(%q) err = %v, want nil", tc.name, err)
			}
			if got != tc.wantText {
				t.Errorf("transcriptDecision(%q) = %q, want %q", tc.name, got, tc.wantText)
			}
		})
	}
}

// parseVoiceSttError turns a failed `voice-keys transcribe` run into one clear
// error: the structured {error} from stderr, a timeout, a missing command, or a
// bare exit failure, so the fallback log names why STT did not answer.
func TestParseVoiceSttError(t *testing.T) {
	exit := &exec.ExitError{}
	notFound := &exec.Error{Name: "voice-keys", Err: exec.ErrNotFound}

	if err := parseVoiceSttError([]byte(`{"error":"STT not configured"}`), exit, false); err == nil ||
		!strings.Contains(err.Error(), "STT not configured") {
		t.Errorf("structured error = %v, want it to carry the stderr reason", err)
	}
	if err := parseVoiceSttError(nil, exit, true); err == nil || !strings.Contains(err.Error(), "timed out") {
		t.Errorf("timeout error = %v, want a timeout message", err)
	}
	if err := parseVoiceSttError(nil, notFound, false); err == nil || !strings.Contains(err.Error(), "PATH") {
		t.Errorf("missing-command error = %v, want a PATH message", err)
	}
	if err := parseVoiceSttError([]byte("not json"), exit, false); err == nil {
		t.Errorf("bare failure error = nil, want a non-nil error")
	}
}
