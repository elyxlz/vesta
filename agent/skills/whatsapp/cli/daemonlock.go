package main

import (
	"os"
	"path/filepath"
	"syscall"
)

const daemonLockFile = "daemon.lock"

// serveDaemonLock holds the exclusive daemon.lock open file for the serve
// process's whole lifetime. It is a package-level reference so the garbage
// collector never finalizes (and thereby closes, releasing the lock) the file
// while the daemon runs.
var serveDaemonLock *os.File

// acquireDaemonLock takes an exclusive, non-blocking OS lock on the per-instance
// daemon.lock file. When the lock is already held (another daemon is serving this
// same device store) it returns ok=false with no error, so the caller can exit
// without ever opening the whatsmeow store, and two connected daemons on one
// device store become structurally impossible (the root of the device-session
// conflict). The returned file is kept open for the process lifetime: the lock
// lives exactly as long as the daemon, releasing only when the process exits.
func acquireDaemonLock(dataDir string) (*os.File, bool, error) {
	file, err := os.OpenFile(filepath.Join(dataDir, daemonLockFile), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return nil, false, err
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		if err == syscall.EWOULDBLOCK {
			return nil, false, nil
		}
		return nil, false, err
	}
	return file, true, nil
}
