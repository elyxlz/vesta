package main

import (
	"runtime"
	"testing"
)

// The whisper Go binding defaults every context to runtime.NumCPU(), so MaxConcurrentTranscriptions
// voice notes at once request that many times more threads than the box has. The budget must stay
// within one machine's worth of threads, and never fall to zero on a single-core host.
func TestWhisperThreadsStaysWithinOneMachine(t *testing.T) {
	threads := whisperThreads()

	if threads < 1 {
		t.Fatalf("whisperThreads() = %d, must be at least 1", threads)
	}
	if threads > WhisperMaxThreads {
		t.Fatalf("whisperThreads() = %d, want at most WhisperMaxThreads (%d)", threads, WhisperMaxThreads)
	}
	if cpus := runtime.NumCPU(); int(threads)*MaxConcurrentTranscriptions > cpus && int(threads) > 1 {
		t.Fatalf("whisperThreads() = %d oversubscribes %d CPUs at %d concurrent transcriptions", threads, cpus, MaxConcurrentTranscriptions)
	}
	if int(threads) >= runtime.NumCPU() && runtime.NumCPU() > WhisperMaxThreads {
		t.Fatalf("whisperThreads() = %d leaves nothing for the daemon on a %d-CPU box", threads, runtime.NumCPU())
	}
}
