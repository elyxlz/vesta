package main

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestScreenOutputHasLiveSession(t *testing.T) {
	live := "There are screens on:\n\t12345.whatsapp\t(Detached)\n\t99.whatsapp-personal\t(Detached)\n2 Sockets in /run/screen/S-root.\n"
	dead := "There are screens on:\n\t12345.whatsapp\t(Dead ???)\nRemove dead screens with 'screen -wipe'.\n"
	cases := []struct {
		name   string
		output string
		want   bool
	}{
		{"whatsapp", live, true},
		{"whatsapp-personal", live, true},
		{"whatsapp", dead, false},
		{"whatsapp", "No Sockets found in /run/screen/S-root.\n", false},
		{"whatsapp-other", live, false},
	}
	for _, tc := range cases {
		if got := screenOutputHasLiveSession(tc.output, tc.name); got != tc.want {
			t.Errorf("screenOutputHasLiveSession(%q session=%q) = %v, want %v", tc.output, tc.name, got, tc.want)
		}
	}
}

func TestStopRefusalDuringSyncWindow(t *testing.T) {
	if msg := stopRefusal(3*time.Minute, false); msg == "" {
		t.Fatal("stop during the sync window without --force must be refused")
	} else if !strings.Contains(msg, "logs the device out") {
		t.Errorf("refusal must explain the consequence, got %q", msg)
	}
	if msg := stopRefusal(3*time.Minute, true); msg != "" {
		t.Errorf("--force must override, got %q", msg)
	}
	if msg := stopRefusal(0, false); msg != "" {
		t.Errorf("no window means no refusal, got %q", msg)
	}
}

func TestRestartReusesRecordedServeFlags(t *testing.T) {
	recorded := daemonInfo{Args: []string{"--instance", "personal", "--read-only", "--no-notifications"}}
	serveArgs, note := restartServeArgs(recorded, nil)
	if !reflect.DeepEqual(serveArgs, recorded.Args) {
		t.Errorf("restart must reuse the recorded serve flags, got %v", serveArgs)
	}
	if note != "" {
		t.Errorf("faithful restart needs no note, got %q", note)
	}
}

func TestRestartWithoutDaemonInfoFallsBackToInstanceArgs(t *testing.T) {
	serveArgs, note := restartServeArgs(daemonInfo{}, errors.New("no daemon-info.json"))
	if len(serveArgs) != 0 {
		t.Errorf("without daemon-info.json the fallback is instance args only, got %v", serveArgs)
	}
	if !strings.Contains(note, "instance args only") {
		t.Errorf("fallback must disclose the flag loss, got %q", note)
	}
}
