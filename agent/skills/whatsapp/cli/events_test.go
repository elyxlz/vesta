package main

import (
	"testing"
	"time"

	"go.mau.fi/whatsmeow/types/events"
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
// is ignored (whatsmeow auto-reconnects), a stream replacement yields, and a
// genuine logout needs a deliberate re-provision, never an auto re-pair loop.
func TestClassifyConnEvent(t *testing.T) {
	cases := []struct {
		name string
		evt  any
		want connEventAction
	}{
		{"disconnected is transient", &events.Disconnected{}, connIgnore},
		{"stream replaced yields", &events.StreamReplaced{}, connYield},
		{"logged out needs provision", &events.LoggedOut{}, connNeedsProvision},
		{"unknown event is ignored", &events.Connected{}, connIgnore},
	}
	for _, tc := range cases {
		if got := classifyConnEvent(tc.evt); got != tc.want {
			t.Errorf("%s: classifyConnEvent = %d, want %d", tc.name, got, tc.want)
		}
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
