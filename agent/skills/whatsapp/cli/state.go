package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const stateFile = "state.json"

// daemonState is the single consolidated on-disk state blob for one WhatsApp
// instance, replacing the former per-concern files (managed-auth, auth-status,
// last-exit, daemon-info, pairing-attempts, linked-at). The serve process is the
// sole writer (through stateStore); transient CLI processes only read it (and only
// when no daemon answers the socket), so the cross-process clobber the split files
// avoided cannot happen, and the atomic temp+rename keeps readers tear-free.
type daemonState struct {
	// Managed number + direct-mode pool creds. DirectURL/DirectKey survive an env
	// scrub: providing them once in the environment persists them here forever.
	MSISDN    string `json:"msisdn,omitempty"`
	DirectURL string `json:"api_url,omitempty"`
	DirectKey string `json:"api_key,omitempty"`
	// FreshPhotoWipePending is armed only after linking a newly claimed (or
	// replacement) managed number. It survives an IQ failure so the next explicit
	// connect retries the idempotent wipe, but routine reconnects never touch it.
	FreshPhotoWipePending bool `json:"fresh_photo_wipe_pending,omitempty"`

	// Auth-status cache, truthful for a cold read when the daemon is down.
	AuthStatus string `json:"auth_status,omitempty"`
	AuthNote   string `json:"auth_note,omitempty"`

	// Why the device session last ended (a logout or a stream-replaced conflict),
	// so status can surface the reason after the daemon has gone quiescent.
	ExitStatus string    `json:"exit_status,omitempty"`
	ExitReason string    `json:"exit_reason,omitempty"`
	ExitTime   time.Time `json:"exit_time,omitempty"`

	// ConnParked records that this device yielded to another connection that took
	// over the session (a StreamReplaced). It persists so a restart does not steal
	// the session back and ping-pong with the other holder; only a deliberate
	// `whatsapp connect` clears it.
	ConnParked bool `json:"conn_parked,omitempty"`

	// The running daemon's serve flags, so `daemon restart` brings it back faithfully.
	Args      []string  `json:"args,omitempty"`
	PID       int       `json:"pid,omitempty"`
	StartedAt time.Time `json:"started_at,omitempty"`

	// Pairing-attempt sliding window (ban-avoidance rate limit).
	PairAttempts []time.Time `json:"pair_attempts,omitempty"`

	// Start of the post-link history-sync window (stop/restart locked while open).
	LinkedAt time.Time `json:"linked_at,omitempty"`

	// Device-preservation reconnect (see preserve.go). RestorePending is set when a
	// preserve-reconnect is in flight and read at boot to restore the last-good
	// device before opening the store; PreserveRetryAt is when the last
	// preserve-reconnect was attempted (the single-retry guard).
	RestorePending  bool      `json:"restore_pending,omitempty"`
	PreserveRetryAt time.Time `json:"preserve_retry_at,omitempty"`

	// ConflictEpisode records that the in-flight preserve episode began as a
	// self-inflicted on-connect "another device" (401) conflict rather than a genuine
	// device_removed. It decides the give-up posture: a conflict episode PARKS with the
	// device preserved (a real other holder is transient), a genuine one CLEARS for a
	// deliberate re-provision. Cleared alongside PreserveRetryAt once the connection
	// proves stable.
	ConflictEpisode bool `json:"conflict_episode,omitempty"`
}

func statePath(dataDir string) string { return filepath.Join(dataDir, stateFile) }

// defaultNotificationsDir is where inbound notification JSON is written when the
// serve flags do not override it.
func defaultNotificationsDir() string {
	return filepath.Join(os.Getenv("HOME"), "agent", "notifications")
}

// stopRequestedPath is a standalone 0-byte IPC marker, not part of state.json: it
// is the one signal the transient `daemon stop` process writes and the dying serve
// process reads. Folding it in would make a second process a blob writer and
// reintroduce the cross-process clobber consolidation removes, so it stays a marker.
func stopRequestedPath(dataDir string) string {
	return filepath.Join(dataDir, "stop-requested")
}

// stateStore owns state.json for the serve process: the authoritative in-memory
// copy, every mutation serialized behind one mutex and persisted atomically. The
// single writer.
type stateStore struct {
	mu   sync.Mutex
	path string
	st   daemonState
}

// newStateStore loads the state (migrating legacy files in memory when needed) and
// converges it to a single state.json, deleting the legacy files. Call it only from
// the serve process (which holds the single-instance lock, so it is the sole writer).
func newStateStore(dataDir string) *stateStore {
	s := &stateStore{path: statePath(dataDir), st: loadStateFromDisk(dataDir)}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.persistLocked(); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to write %s: %v\n", stateFile, err)
	}
	removeLegacyStateFiles(dataDir)
	return s
}

// update applies mut under the lock and atomically persists the result.
func (s *stateStore) update(mut func(*daemonState)) {
	s.mu.Lock()
	defer s.mu.Unlock()
	mut(&s.st)
	if err := s.persistLocked(); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to write %s: %v\n", stateFile, err)
	}
}

// snapshot returns a copy of the current state under the lock.
func (s *stateStore) snapshot() daemonState {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.st
}

func (s *stateStore) persistLocked() error { return atomicWriteJSON(s.path, s.st) }

// tryRecordPairAttempt checks the ban-avoidance rate limit and, when allowed,
// records an attempt, atomically. For callers where initiating the flow IS the
// attempt (a QR link session).
func (s *stateStore) tryRecordPairAttempt(now time.Time, acknowledged bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := checkPairAttempt(s.st.PairAttempts, now, acknowledged); err != nil {
		return err
	}
	s.st.PairAttempts = append(attemptsWithin(s.st.PairAttempts, now, PairRetentionWindow), now)
	return s.persistLocked()
}

// recordPairAttempt appends one attempt. Phone-code pairing checks first and records
// only on a generated code, so a transient pre-connection failure never burns a slot.
func (s *stateStore) recordPairAttempt(now time.Time) {
	s.update(func(st *daemonState) {
		st.PairAttempts = append(attemptsWithin(st.PairAttempts, now, PairRetentionWindow), now)
	})
}

// atomicWriteJSON writes v to path via a unique temp file + rename, so a concurrent
// reader (in this or another process) never sees a torn file.
func atomicWriteJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	f, err := os.CreateTemp(dir, filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	if _, err := f.Write(b); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Chmod(tmp, 0644); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// loadStateFromDisk reads state.json, or derives the blob from the legacy files when
// state.json is absent. Pure read (converging to disk is newStateStore's job, done
// on the serve process). Transient CLI readers use this directly.
func loadStateFromDisk(dataDir string) daemonState {
	if b, err := os.ReadFile(statePath(dataDir)); err == nil {
		var st daemonState
		if json.Unmarshal(b, &st) == nil {
			return st
		}
		// state.json exists but is unreadable. Do NOT fall through to the legacy
		// migration (which returns empty on a converged box and would then be saved
		// over the damaged file, losing MSISDN + pool creds). Preserve the bytes as
		// state.json.corrupt for recovery and start from a SAFE base: salvage the
		// ban-avoidance caps when the bytes still decode, else treat the state as
		// cap-exhausted so a corrupt file never silently reopens the HARD pairing
		// rate limit. MSISDN + pool creds are re-derived by `whatsapp connect`.
		fmt.Fprintf(os.Stderr, "warning: state.json is corrupt; preserving it as state.json.corrupt and starting from a safe base\n")
		os.Rename(statePath(dataDir), statePath(dataDir)+".corrupt")
		return salvageCorruptState(b, time.Now())
	}
	return migrateLegacyState(dataDir)
}

// salvageCorruptState builds a safe daemonState from the bytes of a corrupt
// state.json. It leniently decodes just the ban-avoidance caps (PairAttempts +
// LinkedAt); when even that fails it returns a cap-exhausted window, so a corrupt
// state can never silently zero the HARD pairing rate limit into a clean slate.
func salvageCorruptState(raw []byte, now time.Time) daemonState {
	var lenient struct {
		PairAttempts []time.Time `json:"pair_attempts"`
		LinkedAt     time.Time   `json:"linked_at"`
	}
	if json.Unmarshal(raw, &lenient) == nil {
		return daemonState{PairAttempts: lenient.PairAttempts, LinkedAt: lenient.LinkedAt}
	}
	return daemonState{PairAttempts: exhaustedAttempts(now)}
}

// exhaustedAttempts returns a pairing history that trips every ban-avoidance cap:
// MaxPairPer7d attempts stamped at now, so an unreadable corrupt state defaults to
// cap-exhausted rather than a clean zero that would reopen the hard pairing limit.
func exhaustedAttempts(now time.Time) []time.Time {
	attempts := make([]time.Time, MaxPairPer7d)
	for i := range attempts {
		attempts[i] = now
	}
	return attempts
}

// LEGACY(remove-when: all whatsapp daemons have booted once and written state.json):
// migrateLegacyState and the legacyStateFiles/removeLegacyStateFiles machinery below
// exist only to fold the pre-consolidation per-concern files into state.json on the
// first boot after upgrade; delete once no fleet daemon still carries them on disk.
//
// migrateLegacyState assembles a daemonState from the pre-consolidation files. It
// reads whatever is present and ignores the rest, so a partially-populated legacy
// data dir converges without loss.
func migrateLegacyState(dataDir string) daemonState {
	var st daemonState

	readJSON := func(name string, out any) {
		if b, err := os.ReadFile(filepath.Join(dataDir, name)); err == nil {
			_ = json.Unmarshal(b, out)
		}
	}

	var managed struct {
		MSISDN    string `json:"msisdn"`
		DirectURL string `json:"api_url"`
		DirectKey string `json:"api_key"`
	}
	readJSON("managed-auth.json", &managed)
	st.MSISDN, st.DirectURL, st.DirectKey = managed.MSISDN, managed.DirectURL, managed.DirectKey

	var auth struct {
		Status string `json:"status"`
		Note   string `json:"note"`
	}
	readJSON("auth-status.json", &auth)
	st.AuthStatus, st.AuthNote = auth.Status, auth.Note

	var exit struct {
		Status string    `json:"status"`
		Reason string    `json:"reason"`
		Time   time.Time `json:"time"`
	}
	readJSON("last-exit.json", &exit)
	st.ExitStatus, st.ExitReason, st.ExitTime = exit.Status, exit.Reason, exit.Time

	var info struct {
		Args      []string  `json:"args"`
		PID       int       `json:"pid"`
		StartedAt time.Time `json:"started_at"`
	}
	readJSON("daemon-info.json", &info)
	st.Args, st.PID, st.StartedAt = info.Args, info.PID, info.StartedAt

	readJSON("pairing-attempts.json", &st.PairAttempts)

	if b, err := os.ReadFile(filepath.Join(dataDir, "linked-at")); err == nil {
		if t, perr := time.Parse(time.RFC3339, strings.TrimSpace(string(b))); perr == nil {
			st.LinkedAt = t
		}
	}
	return st
}

// legacyStateFiles are the pre-consolidation files migrateLegacyState folds in.
var legacyStateFiles = []string{
	"managed-auth.json", "auth-status.json", "last-exit.json",
	"daemon-info.json", "pairing-attempts.json", "linked-at",
}

// removeLegacyStateFiles deletes the folded legacy files. Idempotent (a missing
// file is not an error), so re-running after convergence is a no-op.
func removeLegacyStateFiles(dataDir string) {
	for _, name := range legacyStateFiles {
		if err := os.Remove(filepath.Join(dataDir, name)); err != nil && !os.IsNotExist(err) {
			fmt.Fprintf(os.Stderr, "warning: failed to remove legacy %s: %v\n", name, err)
		}
	}
}

// authStatusMap renders the persisted auth status as the map the status/authenticate
// readers expect, attaching the QR image path when a code is pending.
func authStatusMap(st daemonState, dataDir string) map[string]string {
	if st.AuthStatus == "" {
		return map[string]string{"status": "not_started"}
	}
	out := map[string]string{"status": st.AuthStatus}
	if st.AuthNote != "" {
		out["note"] = st.AuthNote
	}
	if st.AuthStatus == string(AuthStatusQRReady) {
		out["qr_image"] = "file://" + filepath.Join(dataDir, "qr-code.png")
	}
	return out
}
