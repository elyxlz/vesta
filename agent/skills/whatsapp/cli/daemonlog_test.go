package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWriterLoggerTeesToWriter(t *testing.T) {
	var buf strings.Builder
	logger := newWriterLogger(&buf, "WhatsApp", "WARN")
	logger.Warnf("device %s conflict", "stream")
	logger.Debugf("this is below the WARN threshold and must be dropped")
	out := buf.String()
	if !strings.Contains(out, "device stream conflict") {
		t.Errorf("warn line missing from log output: %q", out)
	}
	if strings.Contains(out, "below the WARN threshold") {
		t.Errorf("debug line must be filtered out at WARN level: %q", out)
	}
}

// TestOpenDaemonLogTruncatesOversizedFile proves the self-cap: a daemon.log past
// the size limit is truncated at open, so it never grows without bound.
func TestOpenDaemonLogTruncatesOversizedFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, daemonLogFile)
	if err := os.WriteFile(path, make([]byte, daemonLogMaxSize+1), 0644); err != nil {
		t.Fatalf("seed oversized log: %v", err)
	}

	file, err := openDaemonLog(dir)
	if err != nil {
		t.Fatalf("openDaemonLog: %v", err)
	}
	defer file.Close()

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() != 0 {
		t.Errorf("oversized log must be truncated at open, size = %d", info.Size())
	}
}
