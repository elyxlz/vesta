package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// setExitForTest records an exit reason through the state store, the way the
// daemon's yield/logout paths do.
func setExitForTest(dataDir, status, reason string) {
	newStateStore(dataDir).update(func(s *daemonState) {
		s.ExitStatus, s.ExitReason, s.ExitTime = status, reason, time.Now().UTC()
	})
}

func TestStateRoundTrip(t *testing.T) {
	dir := t.TempDir()
	s := newStateStore(dir)
	now := time.Now().UTC().Truncate(time.Second)
	s.update(func(st *daemonState) {
		st.MSISDN = "+447700900001"
		st.AuthStatus = string(AuthStatusAuthenticated)
		st.Args = []string{"--instance", "personal", "--read-only"}
		st.PID = 4242
		st.StartedAt = now
		st.LinkedAt = now
		st.PairAttempts = []time.Time{now}
	})

	got := loadStateFromDisk(dir)
	if got.MSISDN != "+447700900001" || got.AuthStatus != string(AuthStatusAuthenticated) {
		t.Fatalf("round trip lost identity/auth: %+v", got)
	}
	if len(got.Args) != 3 || got.Args[0] != "--instance" || got.PID != 4242 {
		t.Fatalf("round trip lost serve args/pid: %+v", got)
	}
	if !got.StartedAt.Equal(now) || !got.LinkedAt.Equal(now) || len(got.PairAttempts) != 1 {
		t.Fatalf("round trip lost timestamps: %+v", got)
	}
}

// TestMigrateLegacyFiles proves the pre-consolidation files are folded into
// state.json (import-then-remove) with no data loss.
func TestMigrateLegacyFiles(t *testing.T) {
	dir := t.TempDir()
	write := func(name string, v any) {
		b, _ := json.Marshal(v)
		if err := os.WriteFile(filepath.Join(dir, name), b, 0644); err != nil {
			t.Fatal(err)
		}
	}
	linkedAt := time.Now().UTC().Truncate(time.Second)
	write("managed-auth.json", map[string]string{"msisdn": "+447700900009", "api_url": "https://box", "api_key": "wak_x"})
	write("auth-status.json", map[string]string{"status": "authenticated"})
	write("last-exit.json", map[string]any{"status": "stream_replaced", "reason": "took over", "time": linkedAt})
	write("daemon-info.json", map[string]any{"args": []string{"--instance", "p"}, "pid": 7, "started_at": linkedAt})
	write("pairing-attempts.json", []time.Time{linkedAt})
	if err := os.WriteFile(filepath.Join(dir, "linked-at"), []byte(linkedAt.Format(time.RFC3339)), 0644); err != nil {
		t.Fatal(err)
	}

	// Pure read derives the blob without touching disk.
	derived := migrateLegacyState(dir)
	if derived.MSISDN != "+447700900009" || derived.DirectKey != "wak_x" || derived.AuthStatus != "authenticated" {
		t.Fatalf("legacy managed/auth not folded: %+v", derived)
	}
	if derived.ExitStatus != "stream_replaced" || derived.ExitReason != "took over" {
		t.Fatalf("legacy last-exit not folded: %+v", derived)
	}
	if len(derived.Args) != 2 || derived.PID != 7 || len(derived.PairAttempts) != 1 || derived.LinkedAt.IsZero() {
		t.Fatalf("legacy daemon-info/attempts/linked-at not folded: %+v", derived)
	}

	// The serve process converges: state.json written, legacy files removed.
	newStateStore(dir)
	if _, err := os.Stat(filepath.Join(dir, stateFile)); err != nil {
		t.Fatalf("state.json not written after convergence: %v", err)
	}
	for _, name := range legacyStateFiles {
		if _, err := os.Stat(filepath.Join(dir, name)); !os.IsNotExist(err) {
			t.Errorf("legacy file %s should be removed after convergence", name)
		}
	}
	// The consolidated blob still carries the migrated data.
	if got := loadStateFromDisk(dir); got.MSISDN != "+447700900009" || got.ExitReason != "took over" {
		t.Fatalf("converged state lost migrated data: %+v", got)
	}
}

// TestStateJSONWinsOverLegacy proves an existing state.json is authoritative: the
// legacy files are not re-read once consolidation has happened.
func TestStateJSONWinsOverLegacy(t *testing.T) {
	dir := t.TempDir()
	newStateStore(dir).update(func(s *daemonState) { s.MSISDN = "+11111111111" })
	// A stray legacy file must be ignored while state.json exists.
	if err := os.WriteFile(filepath.Join(dir, "managed-auth.json"), []byte(`{"msisdn":"+99999999999"}`), 0644); err != nil {
		t.Fatal(err)
	}
	if got := loadStateFromDisk(dir); got.MSISDN != "+11111111111" {
		t.Fatalf("state.json must win over a stray legacy file, got %q", got.MSISDN)
	}
}

// TestCorruptStatePreservesAndSalvages proves a corrupt state.json is preserved
// aside (never overwritten in place) and never silently reopens the HARD pairing
// caps: unreadable bytes start cap-exhausted, salvageable bytes keep the attempts.
func TestCorruptStatePreservesAndSalvages(t *testing.T) {
	t.Run("unreadable starts safe and cap-exhausted", func(t *testing.T) {
		dir := t.TempDir()
		original := []byte("this is not json {{{")
		if err := os.WriteFile(statePath(dir), original, 0644); err != nil {
			t.Fatal(err)
		}

		got := loadStateFromDisk(dir)

		if got.MSISDN != "" || got.AuthStatus != "" {
			t.Fatalf("a corrupt state must load an empty/safe base: %+v", got)
		}
		// The original bytes are moved aside, not overwritten in place.
		if _, err := os.Stat(statePath(dir)); !os.IsNotExist(err) {
			t.Fatal("the corrupt state.json must be renamed aside, not left in place")
		}
		corrupt, err := os.ReadFile(statePath(dir) + ".corrupt")
		if err != nil {
			t.Fatalf("a .corrupt sidecar must preserve the original bytes: %v", err)
		}
		if string(corrupt) != string(original) {
			t.Fatal("the .corrupt sidecar must hold the original bytes verbatim")
		}
		// Cap-exhausted: the pairing rate limit stays closed, never a clean zero.
		if len(got.PairAttempts) != MaxPairPer7d {
			t.Fatalf("unreadable corrupt state must start cap-exhausted, got %d attempts", len(got.PairAttempts))
		}
		if err := checkPairAttempt(got.PairAttempts, time.Now(), false); err == nil {
			t.Fatal("cap-exhausted state must block a fresh pairing attempt")
		}
	})

	t.Run("salvages pair attempts when partially decodable", func(t *testing.T) {
		dir := t.TempDir()
		attempt := time.Now().UTC().Truncate(time.Second)
		// Valid JSON, but pid is the wrong type so the full daemonState decode fails;
		// pair_attempts is intact and must be salvaged rather than reset to a clean zero.
		raw := fmt.Sprintf(`{"pid":"not-an-int","pair_attempts":[%q]}`, attempt.Format(time.RFC3339))
		if err := os.WriteFile(statePath(dir), []byte(raw), 0644); err != nil {
			t.Fatal(err)
		}

		got := loadStateFromDisk(dir)

		if len(got.PairAttempts) != 1 || !got.PairAttempts[0].Equal(attempt) {
			t.Fatalf("salvage must preserve the decodable pair attempts, got %+v", got.PairAttempts)
		}
	})
}

func TestNewStateStoreWithStatePersistsCorruptSalvage(t *testing.T) {
	dir := t.TempDir()
	now := time.Now().UTC().Truncate(time.Second)
	initial := daemonState{PairAttempts: []time.Time{now}, LinkedAt: now}
	newStateStoreWithState(dir, initial)
	got := loadStateFromDisk(dir)
	if len(got.PairAttempts) != 1 || !got.LinkedAt.Equal(now) {
		t.Fatalf("initial salvaged state was discarded: %+v", got)
	}
}

func TestDefaultNotificationsDir(t *testing.T) {
	want := filepath.Join(os.Getenv("HOME"), "agent", "notifications")
	if got := defaultNotificationsDir(); got != want {
		t.Errorf("defaultNotificationsDir() = %q, want %q", got, want)
	}
}

func TestAuthStatusMap(t *testing.T) {
	dir := t.TempDir()
	if got := authStatusMap(daemonState{}, dir)["status"]; got != "not_started" {
		t.Errorf("empty state status = %q, want not_started", got)
	}
	qr := authStatusMap(daemonState{AuthStatus: string(AuthStatusQRReady)}, dir)
	if qr["status"] != string(AuthStatusQRReady) || qr["qr_image"] == "" {
		t.Errorf("qr_ready must carry a qr_image path: %+v", qr)
	}
	loggedOut := authStatusMap(daemonState{AuthStatus: "logged_out", AuthNote: "unlinked"}, dir)
	if loggedOut["note"] != "unlinked" {
		t.Errorf("note must round-trip: %+v", loggedOut)
	}
}
