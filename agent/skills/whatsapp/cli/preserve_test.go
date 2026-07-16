package main

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// TestDecidePreserve pins the pure preserve decision: no snapshot always gives
// up; with a snapshot the single-retry guard allows a reconnect only when it is
// unset or older than the window.
func TestDecidePreserve(t *testing.T) {
	now := time.Date(2026, 7, 9, 12, 0, 0, 0, time.UTC)
	cases := []struct {
		name        string
		hasSnapshot bool
		lastRetry   time.Time
		want        preserveDecision
	}{
		{"no snapshot gives up", false, time.Time{}, preserveGiveUp},
		{"snapshot + never retried reconnects", true, time.Time{}, preserveReconnect},
		{"snapshot + recent retry gives up", true, now.Add(-10 * time.Minute), preserveGiveUp},
		{"snapshot + old retry reconnects", true, now.Add(-(PreserveRetryWindow + time.Minute)), preserveReconnect},
		{"no snapshot + old retry still gives up", false, now.Add(-time.Hour), preserveGiveUp},
	}
	for _, tc := range cases {
		if got := decidePreserve(tc.hasSnapshot, tc.lastRetry, now); got != tc.want {
			t.Errorf("%s: decidePreserve = %d, want %d", tc.name, got, tc.want)
		}
	}
}

// TestSnapshotRestoreRoundTrip proves a snapshot captures the live device store
// and a restore brings the original rows back while dropping the WAL/SHM sidecars
// (so SQLite cannot replay the removal that lives in the WAL).
func TestSnapshotRestoreRoundTrip(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "whatsapp.db")

	db, err := sql.Open("sqlite3", live)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE device (jid TEXT)`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO device (jid) VALUES ('good-number')`); err != nil {
		t.Fatal(err)
	}
	db.Close()

	snapshotGoodDevice(dir, waLog.Noop)
	if !hasGoodDevice(dir) {
		t.Fatal("snapshot was not created")
	}

	// Simulate whatsmeow's device deletion, and leave stale WAL/SHM sidecars.
	db, err = sql.Open("sqlite3", live)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`DELETE FROM device`); err != nil {
		t.Fatal(err)
	}
	db.Close()
	for _, sidecar := range []string{live + "-wal", live + "-shm"} {
		if err := os.WriteFile(sidecar, []byte("stale"), 0644); err != nil {
			t.Fatal(err)
		}
	}

	if err := restoreGoodDevice(dir, waLog.Noop); err != nil {
		t.Fatalf("restore: %v", err)
	}

	for _, sidecar := range []string{live + "-wal", live + "-shm"} {
		if _, err := os.Stat(sidecar); !os.IsNotExist(err) {
			t.Errorf("%s should be removed after restore", sidecar)
		}
	}

	db, err = sql.Open("sqlite3", live)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var jid string
	if err := db.QueryRow(`SELECT jid FROM device`).Scan(&jid); err != nil {
		t.Fatalf("original row not restored: %v", err)
	}
	if jid != "good-number" {
		t.Errorf("restored jid = %q, want good-number", jid)
	}
}
