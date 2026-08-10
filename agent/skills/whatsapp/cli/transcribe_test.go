package main

import "testing"

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
// treated as junk so we fall back to Deepgram, while a real transcript that
// merely contains a bracketed word must NOT be dropped. The regex anchors to
// the whole string, which is what makes the distinction.
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
