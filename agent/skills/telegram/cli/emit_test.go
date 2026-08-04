package main

import (
	"io"
	"os"
	"testing"
)

func captureStreams(t *testing.T, fn func()) (stdout, stderr string) {
	t.Helper()
	origOut, origErr := os.Stdout, os.Stderr
	outRead, outWrite, err := os.Pipe()
	if err != nil {
		t.Fatalf("failed to open stdout pipe: %v", err)
	}
	errRead, errWrite, err := os.Pipe()
	if err != nil {
		t.Fatalf("failed to open stderr pipe: %v", err)
	}
	os.Stdout, os.Stderr = outWrite, errWrite
	fn()
	os.Stdout, os.Stderr = origOut, origErr
	outWrite.Close()
	errWrite.Close()
	outBytes, _ := io.ReadAll(outRead)
	errBytes, _ := io.ReadAll(errRead)
	return string(outBytes), string(errBytes)
}

// emit owns the stream contract: stdout carries only success output, and anything
// paired with a non-zero exit prints to stderr, so a filter piped onto stdout can
// never swallow a failure's envelope.
func TestEmitRoutesByOutcome(t *testing.T) {
	cases := []struct {
		name       string
		data       string
		exitCode   int
		wantStdout string
		wantStderr string
	}{
		{
			name:       "success prints on stdout only",
			data:       `{"success": true}`,
			exitCode:   0,
			wantStdout: "{\"success\": true}\n",
			wantStderr: "",
		},
		{
			name:       "failure prints on stderr only",
			data:       `{"error": "daemon not running; start with: telegram daemon start"}`,
			exitCode:   1,
			wantStdout: "",
			wantStderr: "{\"error\": \"daemon not running; start with: telegram daemon start\"}\n",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stdout, stderr := captureStreams(t, func() { emit([]byte(tc.data), tc.exitCode) })
			if stdout != tc.wantStdout {
				t.Errorf("stdout = %q, want %q", stdout, tc.wantStdout)
			}
			if stderr != tc.wantStderr {
				t.Errorf("stderr = %q, want %q", stderr, tc.wantStderr)
			}
		})
	}
}
