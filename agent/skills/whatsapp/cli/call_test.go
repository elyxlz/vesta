package main

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"testing"

	meowcaller "github.com/purpshell/meowcaller"
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

func TestPCMSourceFramesAndZeroPadsThenEOF(t *testing.T) {
	// 2000 samples -> two full FrameSamples frames plus a short final frame, zero-padded to full
	// length, then io.EOF.
	total := 2*meowcaller.FrameSamples + 80
	samples := make([]float32, total)
	for i := range samples {
		samples[i] = 0.1
	}
	src := newPCMSource(samples)

	for frameNum := 0; frameNum < 3; frameNum++ {
		frame, err := src.ReadFrame()
		if err != nil {
			t.Fatalf("frame %d: unexpected error %v", frameNum, err)
		}
		if len(frame) != meowcaller.FrameSamples {
			t.Fatalf("frame %d: length %d want %d", frameNum, len(frame), meowcaller.FrameSamples)
		}
	}
	// The final frame's tail past the 80 real samples must be silence (zero-padded).
	// Re-read is exhausted.
	if _, err := src.ReadFrame(); err != io.EOF {
		t.Fatalf("expected io.EOF after draining, got %v", err)
	}
}

func TestPCMSourceLastFrameZeroPadsTail(t *testing.T) {
	samples := []float32{0.5, 0.5, 0.5}
	frame, err := newPCMSource(samples).ReadFrame()
	if err != nil {
		t.Fatalf("unexpected error %v", err)
	}
	if len(frame) != meowcaller.FrameSamples {
		t.Fatalf("length %d want %d", len(frame), meowcaller.FrameSamples)
	}
	for i := 3; i < len(frame); i++ {
		if frame[i] != 0 {
			t.Fatalf("tail sample %d not zero-padded: %v", i, frame[i])
		}
	}
}

func TestSayWithoutActiveCallErrors(t *testing.T) {
	cm := &CallManager{}
	if _, err := cm.Say("hello"); err == nil {
		t.Fatal("expected an error saying into a call with no active call")
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
		Transcript:   "are you there",
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
	if got.Type != "call_utterance" || got.Transcript != "are you there" || got.ContactName != "Alice" {
		t.Errorf("notification fields not preserved: %+v", got)
	}
	if got.Instance != "personal" {
		t.Errorf("instance = %q, want personal", got.Instance)
	}
	if got.Timestamp == "" {
		t.Error("timestamp not stamped")
	}
}
