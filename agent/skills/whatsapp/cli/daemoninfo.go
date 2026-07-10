package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

const daemonInfoFile = "daemon-info.json"

type daemonInfo struct {
	Args      []string  `json:"args"`
	PID       int       `json:"pid"`
	StartedAt time.Time `json:"started_at"`
}

func defaultNotificationsDir() string {
	return filepath.Join(os.Getenv("HOME"), "agent", "notifications")
}

func stopRequestedPath(dataDir string) string {
	return filepath.Join(dataDir, "stop-requested")
}

func writeDaemonInfo(dataDir string, serveArgs []string) {
	info := daemonInfo{Args: serveArgs, PID: os.Getpid(), StartedAt: time.Now().UTC()}
	data, err := json.Marshal(info)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to marshal daemon info: %v\n", err)
		return
	}
	if err := os.WriteFile(filepath.Join(dataDir, daemonInfoFile), data, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to write daemon info: %v\n", err)
	}
}

func readDaemonInfo(dataDir string) (daemonInfo, error) {
	var info daemonInfo
	data, err := os.ReadFile(filepath.Join(dataDir, daemonInfoFile))
	if err != nil {
		return info, err
	}
	if err := json.Unmarshal(data, &info); err != nil {
		return info, err
	}
	return info, nil
}
