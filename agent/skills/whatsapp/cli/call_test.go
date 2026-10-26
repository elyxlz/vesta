package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func TestPCM16RoundTripPreservesSamples(t *testing.T) {
	in := []float32{0, 0.5, -0.5, 1, -1, 0.25}
	got := pcm16ToFloat(floatFrameToPCM16(in))
	if len(got) != len(in) {
		t.Fatalf("length changed: got %d want %d", len(got), len(in))
	}
	for i := range in {
		if diff := got[i] - in[i]; diff > 1.0/32768 || diff < -1.0/32768 {
			t.Errorf("sample %d: got %v want %v", i, got[i], in[i])
		}
	}
}

func TestFloatFrameToPCM16ClampsOutOfRange(t *testing.T) {
	// A hot sample above 1.0 must clamp to full-scale, not wrap around to a negative value.
	got := pcm16ToFloat(floatFrameToPCM16([]float32{2.0, -2.0}))
	if got[0] < 0.99 {
		t.Errorf("positive overshoot did not clamp high: got %v", got[0])
	}
	if got[1] > -0.99 {
		t.Errorf("negative overshoot did not clamp low: got %v", got[1])
	}
}

func TestSayWithoutActiveCallErrors(t *testing.T) {
	cm := &CallManager{}
	if _, err := cm.Say("hello"); err == nil {
		t.Fatal("expected an error saying into a call with no active call")
	}
}

// bridgedCall starts the bridge of an answered inbound call from Alice against the fake engine,
// and returns the manager and the directory its notifications land in. The call is a bare
// meowcaller.Call: it takes the bridge's sink and player, and no media loop runs on it.
func bridgedCall(t *testing.T, engine *fakeEngine) (*CallManager, string) {
	t.Helper()
	dir := t.TempDir()
	cm := &CallManager{wac: &WhatsAppClient{notificationsDir: dir, instance: "personal", logger: waLog.Noop}}
	peer := types.NewJID("15551234567", types.DefaultUserServer)
	ac := cm.beginLocked(&meowcaller.Call{}, peer, "Alice", "+15551234567", "inbound", engine.url)
	ac.answered = true
	cm.startBridge(ac)
	t.Cleanup(func() {
		ac.cancel()
		<-ac.voice.done
	})
	return cm, dir
}

func TestTurnEndBecomesOneCallUtteranceNotification(t *testing.T) {
	engine := startFakeEngine(t)
	_, dir := bridgedCall(t, engine)
	side := engine.session(t)

	side.send(map[string]any{"type": "turn_start"})
	side.send(map[string]any{"type": "turn_end", "text": "are you there"})
	// The bridge handles the frames in order, so its answer to an empty play says that the turn
	// before it was handled.
	side.send(map[string]any{"type": "play", "id": "marker", "format": "pcm_16000"})
	side.send(map[string]any{"type": "play_done", "id": "marker"})
	await(t, engine.text, "the report of the marker play")

	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatalf("expected one notification file, got %d (%v)", len(entries), err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, entries[0].Name()))
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	var got callNotif
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("notification is not valid json: %v", err)
	}
	if got.Type != "call_utterance" || got.Message != "are you there" || got.ContactName != "Alice" || got.Direction != "inbound" {
		t.Errorf("notification fields are wrong: %+v", got)
	}
}

func TestSayOnABridgedCallAnswersSpeakingWhenItsAudioArrives(t *testing.T) {
	engine := startFakeEngine(t)
	cm, _ := bridgedCall(t, engine)
	side := engine.session(t)

	type answer struct {
		result any
		err    error
	}
	said := make(chan answer, 1)
	go func() {
		result, err := cm.Say("Hello Alice.")
		said <- answer{result, err}
	}()
	side.play(side.speakID("Hello Alice."), tone(0.1, 1))

	got := await(t, said, "say to return")
	want := map[string]any{"status": "speaking", "contact_name": "Alice"}
	if got.err != nil || !reflect.DeepEqual(got.result, want) {
		t.Fatalf("say = %+v, want %v", got, want)
	}
}

// TestPlaceBlocksManagedColdCall proves an outbound call from a managed number is
// refused before it dials when the peer has never messaged first (reply-first), and
// goes through once an inbound exists. The gate runs before meowcaller is touched, so
// a nil mc never dereferences on the blocked path.
func TestPlaceBlocksManagedColdCall(t *testing.T) {
	wac := newGateTestClient(t, true)
	cm := &CallManager{wac: wac}

	_, err := cm.Place(gateTestPhone)
	if err == nil {
		t.Fatal("managed number must not cold-call a peer that has not messaged first")
	}
	if !strings.Contains(err.Error(), "reply-first") {
		t.Errorf("block must cite reply-first, got: %v", err)
	}

	// After an inbound the gate passes; the call then fails on the nil meowcaller
	// client, which proves dialing was reached rather than blocked at the gate.
	storeInbound(t, wac)
	if err := wac.requireSendAllowed(types.NewJID("15557654321", types.DefaultUserServer)); err != nil {
		t.Errorf("managed number must be allowed to call once the peer has messaged first: %v", err)
	}
}

func TestStatusReportsIdleWhenNoCall(t *testing.T) {
	cm := &CallManager{}
	result, err := cm.Status()
	if err != nil {
		t.Fatalf("unexpected error %v", err)
	}
	status, ok := result.(map[string]any)
	if !ok {
		t.Fatalf("unexpected result type %T", result)
	}
	if status["active"] != false {
		t.Errorf("expected active=false, got %v", status["active"])
	}
}

func TestWriteCallNotificationShapesFileForTheModel(t *testing.T) {
	dir := t.TempDir()
	err := writeCallNotification(dir, "personal", callNotif{
		Type:         "call_utterance",
		Direction:    "inbound",
		ContactName:  "Alice",
		ContactPhone: "+15551234567",
		Message:      "are you there",
	})
	if err != nil {
		t.Fatalf("write failed: %v", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatalf("expected one notification file, got %d (%v)", len(entries), err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, entries[0].Name()))
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	var got callNotif
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("notification is not valid json: %v", err)
	}
	if got.Source != "whatsapp" {
		t.Errorf("source = %q, want whatsapp (so it reaches the model through the whatsapp flow)", got.Source)
	}
	if got.Type != "call_utterance" || got.Message != "are you there" || got.ContactName != "Alice" {
		t.Errorf("notification fields not preserved: %+v", got)
	}
	if got.Instance != "personal" {
		t.Errorf("instance = %q, want personal", got.Instance)
	}
	if got.Timestamp == "" {
		t.Error("timestamp not stamped")
	}
}

// Core promotes `message` to the notification's body and renders every other key as an
// attribute, so the key name is what decides whether the caller's words read like a text
// message or like metadata hung off one.
func TestCallUtteranceCarriesSpokenWordsUnderTheMessageKey(t *testing.T) {
	dir := t.TempDir()
	if err := writeCallNotification(dir, "personal", callNotif{
		Type: "call_utterance", Direction: "inbound", ContactName: "Alice", Message: "are you there",
	}); err != nil {
		t.Fatalf("write failed: %v", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatalf("expected one notification file, got %d (%v)", len(entries), err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, entries[0].Name()))
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		t.Fatalf("notification is not valid json: %v", err)
	}

	var message string
	if err := json.Unmarshal(fields["message"], &message); err != nil || message != "are you there" {
		t.Errorf("message = %q, want the spoken words under the same key a text message uses", message)
	}
	if _, present := fields["transcript"]; present {
		t.Errorf("transcript key is present; it would render as an attribute instead of the body")
	}
}

// The other three call types say nothing, so they carry no body at all.
func TestCallNotificationsWithNothingSpokenCarryNoMessage(t *testing.T) {
	for _, notifType := range []string{"call_started", "call_ended", "call_missed"} {
		dir := t.TempDir()
		if err := writeCallNotification(dir, "personal", callNotif{
			Type: notifType, Direction: "inbound", ContactName: "Alice", Reason: "no answer",
		}); err != nil {
			t.Fatalf("write failed: %v", err)
		}
		entries, _ := os.ReadDir(dir)
		raw, err := os.ReadFile(filepath.Join(dir, entries[0].Name()))
		if err != nil {
			t.Fatalf("read failed: %v", err)
		}
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			t.Fatalf("notification is not valid json: %v", err)
		}
		if _, present := fields["message"]; present {
			t.Errorf("%s carries a message key, want it absent: nothing was said", notifType)
		}
	}
}

func TestRequireCallMgrReadOnlyNamesReadOnly(t *testing.T) {
	_, err := requireCallMgr(&WhatsAppClient{readOnly: true})
	if err == nil || !strings.Contains(err.Error(), "read-only") {
		t.Fatalf("read-only instance: got %v, want a read-only error", err)
	}
	_, err = requireCallMgr(&WhatsAppClient{})
	if err == nil || strings.Contains(err.Error(), "read-only") {
		t.Fatalf("writable instance without a manager: got %v, want the daemon-only error", err)
	}
}
