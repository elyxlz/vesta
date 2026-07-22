package main

import (
	"database/sql"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// Device preservation turns a (frequently spurious) WhatsApp `device_removed`
// into a single restore-and-reconnect instead of a re-pair. whatsmeow deletes
// the local device store the moment the server sends the removal, BEFORE our
// handler runs, so recovery leans on a periodically refreshed snapshot of the
// last-good device store. Restoring + reconnecting is NOT re-pairing, so it adds
// no ban risk; a genuinely dead device re-drops fast and falls back to today's
// park+provision behavior.
const (
	goodDeviceSuffix = ".good"

	// SnapshotMinInterval throttles the good-device snapshot so a reconnect storm
	// cannot spin the disk.
	SnapshotMinInterval = 2 * time.Minute
	// PreserveRetryWindow bounds the single-retry guard: a preserve-reconnect is
	// allowed at most once per window, so a genuinely dead device cannot loop.
	PreserveRetryWindow = 30 * time.Minute
	// StableConnDuration is how long a connection must hold before the retry guard
	// clears, proving the last preserve-reconnect actually recovered the session.
	StableConnDuration = 10 * time.Minute
)

// goodDevicePath is the snapshot path for the last-good whatsmeow device store.
func goodDevicePath(dataDir string) string {
	return filepath.Join(dataDir, "whatsapp.db"+goodDeviceSuffix)
}

// whatsappDBPath is the live whatsmeow device store.
func whatsappDBPath(dataDir string) string {
	return filepath.Join(dataDir, "whatsapp.db")
}

// snapshotGoodDevice writes a consistent copy of the live device store to the
// `.good` snapshot. It opens a SEPARATE read-only connection and uses VACUUM
// INTO, which reads a consistent image even under WAL while the daemon holds the
// DB open. Best-effort: any failure is logged, never fatal.
func snapshotGoodDevice(dataDir string, logger waLog.Logger) {
	src := whatsappDBPath(dataDir)
	if _, err := os.Stat(src); err != nil {
		return
	}
	db, err := sql.Open("sqlite3", fmt.Sprintf("file:%s?_busy_timeout=5000&mode=ro", src))
	if err != nil {
		logger.Warnf("snapshot: open device store failed: %v", err)
		return
	}
	defer db.Close()

	tmp := filepath.Join(dataDir, fmt.Sprintf(".whatsapp.db.good.%d.tmp", time.Now().UnixNano()))
	if _, err := db.Exec("VACUUM INTO ?", tmp); err != nil {
		os.Remove(tmp)
		logger.Warnf("snapshot: VACUUM INTO failed: %v", err)
		return
	}
	if err := os.Rename(tmp, goodDevicePath(dataDir)); err != nil {
		os.Remove(tmp)
		logger.Warnf("snapshot: rename snapshot failed: %v", err)
	}
}

// hasGoodDevice reports whether a last-good device snapshot exists.
func hasGoodDevice(dataDir string) bool {
	_, err := os.Stat(goodDevicePath(dataDir))
	return err == nil
}

// restoreGoodDevice copies the last-good snapshot over the live device store and
// removes the WAL/SHM sidecars so SQLite cannot replay the removal that lives in
// the WAL. MUST be called only at boot, BEFORE the whatsmeow store is opened.
func restoreGoodDevice(dataDir string, logger waLog.Logger) error {
	good := goodDevicePath(dataDir)
	live := whatsappDBPath(dataDir)

	tmp := filepath.Join(dataDir, fmt.Sprintf(".whatsapp.db.restore.%d.tmp", time.Now().UnixNano()))
	if err := copyFile(good, tmp); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("copy snapshot: %w", err)
	}
	if err := os.Rename(tmp, live); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("swap in snapshot: %w", err)
	}
	for _, sidecar := range []string{live + "-wal", live + "-shm"} {
		if err := os.Remove(sidecar); err != nil && !os.IsNotExist(err) {
			logger.Warnf("restore: remove %s failed: %v", sidecar, err)
		}
	}
	return nil
}

// copyFile copies src to dst byte-for-byte (dst is a temp path in the same dir,
// swapped in by an atomic rename).
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

// preserveDecision is what handleDeviceRemoved does with a device removal.
type preserveDecision int

const (
	// preserveReconnect: restore the last-good device and reconnect once.
	preserveReconnect preserveDecision = iota
	// preserveGiveUp: today's park+provision behavior (a real, repeated removal).
	preserveGiveUp
)

// decidePreserve chooses between a one-shot restore-and-reconnect and today's
// give-up. A snapshot is required, and the single-retry guard blocks a second
// preserve-reconnect until the window has elapsed (so a genuinely dead device,
// which re-drops before StableConnDuration keeps PreserveRetryAt fresh, falls
// through to give-up). Pure, unit-tested.
func decidePreserve(hasSnapshot bool, lastRetry, now time.Time) preserveDecision {
	if hasSnapshot && (lastRetry.IsZero() || now.Sub(lastRetry) > PreserveRetryWindow) {
		return preserveReconnect
	}
	return preserveGiveUp
}

// removalAction routes a device removal to its terminal action once decidePreserve has run.
type removalAction int

const (
	removalReconnect removalAction = iota // restore the last-good device and reconnect once
	removalPark                           // preserve the device and park (a persisted on-connect conflict)
	removalClear                          // clear the dead device and exit for a deliberate re-provision
)

// decideRemoval routes a device removal. A fresh episode (decidePreserve ==
// preserveReconnect) always reconnects once. A give-up PARKS when the episode began as a
// self-inflicted on-connect "another device" conflict (the device is fine; a real other
// holder is handled like a StreamReplaced yield, never a clear), and otherwise CLEARS for a
// deliberate re-provision (a genuine phone-side unlink). Pure, unit-tested.
func decideRemoval(preserve preserveDecision, conflictEpisode bool) removalAction {
	if preserve == preserveReconnect {
		return removalReconnect
	}
	if conflictEpisode {
		return removalPark
	}
	return removalClear
}

// reExecDaemon restarts the serve process in place (same PID, so the surrounding
// `screen` session survives) after a preserve-reconnect flag has been set. The
// re-exec'd process runs runServe again, which restores the last-good device
// before opening the store, then reconnects. Does not return on success.
func (wac *WhatsAppClient) reExecDaemon() {
	wac.client.Disconnect()
	// Let WhatsApp register the old socket's teardown before the re-exec'd process
	// reconnects: re-connecting into a still-live server-side session is what re-fires
	// the "logged out from another device" (401) conflict and churns the daemon to
	// unpaired. A short settle removes that overlap (a no-op for a re-exec that comes
	// back parked and never reconnects).
	time.Sleep(ReExecSettleDelay)
	if serveDaemonLock != nil {
		serveDaemonLock.Close()
	}
	bin, err := os.Executable()
	if err != nil {
		bin = os.Args[0]
	}
	// main() strips the "serve" subcommand off os.Args before runServe, so os.Args
	// is now [bin, <serve flags>]. Re-prepend "serve" or the re-exec'd process
	// would read the first flag as its command and never run the daemon.
	argv := append([]string{os.Args[0], "serve"}, os.Args[1:]...)
	if err := syscall.Exec(bin, argv, os.Environ()); err != nil {
		wac.logger.Errorf("re-exec failed (%v); falling back to exit for supervised restart", err)
		if wac.notificationsDir != "" {
			writeDeathNotification(wac.notificationsDir, "device_removed_preserve")
		}
		os.Exit(1)
	}
}

// maybeSnapshotGoodDevice takes a good-device snapshot in the background,
// throttled to at most one per SnapshotMinInterval.
func (wac *WhatsAppClient) maybeSnapshotGoodDevice() {
	wac.preserveMu.Lock()
	if !wac.lastSnapshot.IsZero() && time.Since(wac.lastSnapshot) < SnapshotMinInterval {
		wac.preserveMu.Unlock()
		return
	}
	wac.lastSnapshot = time.Now()
	wac.preserveMu.Unlock()
	go snapshotGoodDevice(wac.dataDir, wac.logger)
}

// snapshotGoodDeviceNow forces a good-device snapshot immediately, bypassing the
// throttle. Used on a fresh link: the pre-pair events.Connected fires while the device
// is still unpaired (Store.ID nil) and snapshots an UNPAIRED store, so without an
// unthrottled snapshot of the now-paired device a conflict within SnapshotMinInterval of
// linking would restore an unpaired device and land unpaired anyway.
func (wac *WhatsAppClient) snapshotGoodDeviceNow() {
	wac.preserveMu.Lock()
	wac.lastSnapshot = time.Now()
	wac.preserveMu.Unlock()
	go snapshotGoodDevice(wac.dataDir, wac.logger)
}

// armStableTimer (re)starts the stability timer: after StableConnDuration of
// continued connection it clears the single-retry guard, proving the last
// preserve-reconnect recovered the session.
func (wac *WhatsAppClient) armStableTimer() {
	wac.preserveMu.Lock()
	defer wac.preserveMu.Unlock()
	if wac.stableTimer != nil {
		wac.stableTimer.Stop()
	}
	wac.stableTimer = time.AfterFunc(StableConnDuration, func() {
		wac.state.update(func(s *daemonState) {
			s.PreserveRetryAt = time.Time{}
			s.ConflictEpisode = false
		})
	})
}

// stopStableTimer cancels the stability timer on any disconnect, so a brief
// connect that drops before StableConnDuration keeps PreserveRetryAt fresh.
func (wac *WhatsAppClient) stopStableTimer() {
	wac.preserveMu.Lock()
	defer wac.preserveMu.Unlock()
	if wac.stableTimer != nil {
		wac.stableTimer.Stop()
		wac.stableTimer = nil
	}
}
