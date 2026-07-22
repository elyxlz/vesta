package main

import (
	"os"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// TestEnqueueWorkOffloadsSlowHandler proves the data-plane offload keeps a slow
// handler off the caller: enqueueWork returns promptly even when the handler
// blocks, and the work still runs once unblocked.
func TestEnqueueWorkOffloadsSlowHandler(t *testing.T) {
	wac := &WhatsAppClient{
		msgWork:    make(chan func(), MsgWorkBuffer),
		workerDone: make(chan struct{}),
	}
	go wac.runMsgWorker()
	defer close(wac.workerDone)

	release := make(chan struct{})
	ran := make(chan struct{})
	returned := make(chan struct{})

	go func() {
		wac.enqueueWork(func() {
			<-release
			close(ran)
		})
		close(returned)
	}()

	select {
	case <-returned:
	case <-time.After(time.Second):
		t.Fatal("enqueueWork blocked on a slow handler")
	}

	close(release)
	select {
	case <-ran:
	case <-time.After(time.Second):
		t.Fatal("enqueued work did not run after unblocking")
	}
}

// TestClassifyConnEvent pins the churn-free logout policy: a transient disconnect
// is ignored (whatsmeow auto-reconnects), a stream replacement yields, a genuine
// logout needs a deliberate re-provision, and a self-inflicted on-connect "another
// device" (401) conflict recovers in place instead of re-pairing.
func TestClassifyConnEvent(t *testing.T) {
	cases := []struct {
		name string
		evt  any
		want connEventAction
	}{
		{"disconnected is transient", &events.Disconnected{}, connIgnore},
		{"stream replaced yields", &events.StreamReplaced{}, connYield},
		{"stream:error logout needs provision", &events.LoggedOut{OnConnect: false}, connNeedsProvision},
		{"on-connect 401 conflict recovers", &events.LoggedOut{OnConnect: true, Reason: events.ConnectFailureLoggedOut}, connRecoverConflict},
		{"on-connect primary-gone needs provision", &events.LoggedOut{OnConnect: true, Reason: events.ConnectFailureMainDeviceGone}, connNeedsProvision},
		{"unknown event is ignored", &events.Connected{}, connIgnore},
	}
	for _, tc := range cases {
		if got := classifyConnEvent(tc.evt); got != tc.want {
			t.Errorf("%s: classifyConnEvent = %d, want %d", tc.name, got, tc.want)
		}
	}
}

// TestIsConflictLogout pins the conflict discriminator: only an ON-CONNECT 401 "logged
// out from another device" is the recoverable self-inflicted overlap; a stream:error
// logout (OnConnect=false) and any other on-connect reason stay terminal.
func TestIsConflictLogout(t *testing.T) {
	cases := []struct {
		name string
		evt  *events.LoggedOut
		want bool
	}{
		{"on-connect 401 is a conflict", &events.LoggedOut{OnConnect: true, Reason: events.ConnectFailureLoggedOut}, true},
		{"stream:error 401 is genuine", &events.LoggedOut{OnConnect: false, Reason: events.ConnectFailureLoggedOut}, false},
		{"on-connect primary-gone is genuine", &events.LoggedOut{OnConnect: true, Reason: events.ConnectFailureMainDeviceGone}, false},
		{"on-connect ban is genuine", &events.LoggedOut{OnConnect: true, Reason: events.ConnectFailureUnknownLogout}, false},
	}
	for _, tc := range cases {
		if got := isConflictLogout(tc.evt); got != tc.want {
			t.Errorf("%s: isConflictLogout = %v, want %v", tc.name, got, tc.want)
		}
	}
}

// TestMarkPreserveReconnectPersists proves the preserve-reconnect side-effect arms the
// boot restore + single-retry guard and records the episode origin, so the give-up posture
// (park for a conflict, clear for a genuine removal) survives the re-exec.
func TestMarkPreserveReconnectPersists(t *testing.T) {
	for _, conflict := range []bool{true, false} {
		wac := &WhatsAppClient{state: newStateStore(t.TempDir())}
		wac.markPreserveReconnect(conflict)
		st := wac.state.snapshot()
		if !st.RestorePending {
			t.Fatal("preserve-reconnect must arm the boot restore")
		}
		if st.PreserveRetryAt.IsZero() {
			t.Fatal("preserve-reconnect must arm the single-retry guard")
		}
		if st.ConflictEpisode != conflict {
			t.Fatalf("preserve-reconnect must record the episode origin: got %v, want %v", st.ConflictEpisode, conflict)
		}
	}
}

// TestMarkConflictParkPreservesTheDevice proves a persisted on-connect conflict PARKS with
// the device preserved: it arms the boot restore, parks (so no reconnect steals the
// session), records the reason, closes the episode, and notifies once. Crucially it never
// clears the device, so a transient overlap cannot churn a linked companion to unpaired.
func TestMarkConflictParkPreservesTheDevice(t *testing.T) {
	notifDir := t.TempDir()
	wac := &WhatsAppClient{
		state:            newStateStore(t.TempDir()),
		notificationsDir: notifDir,
		instance:         "personal",
		logger:           waLog.Noop,
	}
	wac.state.update(func(s *daemonState) {
		s.PreserveRetryAt = time.Now().UTC()
		s.ConflictEpisode = true
	})

	wac.markConflictPark("logged out on connect: logged out from another device")

	st := wac.state.snapshot()
	if !st.RestorePending {
		t.Fatal("conflict park must arm the boot restore so the deleted device is brought back")
	}
	if !st.ConnParked {
		t.Fatal("conflict park must park so no reconnect steals the session back")
	}
	if st.AuthStatus == "logged_out" {
		t.Fatal("conflict park must NOT record the logged_out (cleared) posture; the device is preserved")
	}
	if st.ExitReason == "" {
		t.Fatal("conflict park must record why the session ended")
	}
	if !st.PreserveRetryAt.IsZero() || st.ConflictEpisode {
		t.Fatalf("conflict park must close the episode: %+v", st)
	}

	entries, err := os.ReadDir(notifDir)
	if err != nil {
		t.Fatal(err)
	}
	loggedOut := 0
	for _, e := range entries {
		if strings.Contains(e.Name(), "logged_out") {
			loggedOut++
		}
	}
	if loggedOut != 1 {
		t.Fatalf("conflict park must notify the agent exactly once to reconnect, got %d", loggedOut)
	}
}

// TestApplyYieldParksAndPersists proves the yield side-effect persists the park (so
// a restart honors it), records the exit reason, and resets presence.
func TestApplyYieldParksAndPersists(t *testing.T) {
	wac := &WhatsAppClient{state: newStateStore(t.TempDir())}
	wac.presenceActive = true

	wac.applyYield("another connection took over this device session")

	if !wac.connModeIs(connParked) {
		t.Fatal("yield must park the in-memory posture")
	}
	st := wac.state.snapshot()
	if !st.ConnParked {
		t.Fatal("yield must persist the parked posture so a restart does not steal the session back")
	}
	if st.ExitStatus != "stream_replaced" || st.ExitReason != "another connection took over this device session" {
		t.Fatalf("yield must record the exit reason: %+v", st)
	}
	if wac.presenceActive {
		t.Fatal("yield must reset presence")
	}
}

// TestRecordDeviceLoggedOutPersistsAndNotifies proves the device-removed give-up
// side-effect records the logged_out posture, keeps MSISDN for a same-number reauth,
// closes the preserve episode, and writes exactly one logged_out notification.
func TestRecordDeviceLoggedOutPersistsAndNotifies(t *testing.T) {
	notifDir := t.TempDir()
	wac := &WhatsAppClient{
		state:            newStateStore(t.TempDir()),
		notificationsDir: notifDir,
		instance:         "personal",
		logger:           waLog.Noop,
	}
	wac.state.update(func(s *daemonState) {
		s.MSISDN = "+447700900001"
		s.PreserveRetryAt = time.Now().UTC()
	})

	wac.recordDeviceLoggedOut("unlinked from the phone (stream:error logout)")

	st := wac.state.snapshot()
	if st.AuthStatus != "logged_out" || st.ExitStatus != "logged_out" {
		t.Fatalf("device removal must record the logged_out posture: %+v", st)
	}
	if st.MSISDN != "+447700900001" {
		t.Fatal("device removal must keep MSISDN so the next provision re-links the same number")
	}
	if !st.PreserveRetryAt.IsZero() {
		t.Fatal("device removal must close the preserve episode")
	}

	entries, err := os.ReadDir(notifDir)
	if err != nil {
		t.Fatal(err)
	}
	loggedOut := 0
	for _, e := range entries {
		if strings.Contains(e.Name(), "logged_out") {
			loggedOut++
		}
	}
	if loggedOut != 1 {
		t.Fatalf("device removal must write exactly one logged_out notification, got %d", loggedOut)
	}
}

func TestLoggedOutReason(t *testing.T) {
	onConnect := loggedOutReason(&events.LoggedOut{OnConnect: true, Reason: events.ConnectFailureLoggedOut})
	if onConnect == "" {
		t.Fatal("an on-connect logout must carry a reason")
	}
	offConnect := loggedOutReason(&events.LoggedOut{OnConnect: false})
	if offConnect == "" {
		t.Fatal("a stream:error logout must carry a reason")
	}
}
