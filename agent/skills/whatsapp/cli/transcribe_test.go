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
