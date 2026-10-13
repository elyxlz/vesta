package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// How long a test waits for something that must happen before it fails.
const engineTestWait = 5 * time.Second

func await[T any](t *testing.T, from <-chan T, what string) T {
	t.Helper()
	select {
	case value := <-from:
		return value
	case <-time.After(engineTestWait):
		t.Fatalf("timed out waiting for %s", what)
		panic("unreachable")
	}
}

// fakeEngine is a local stand-in for the voice engine socket. It records what the client sends,
// and the test writes the engine's frames by hand.
type fakeEngine struct {
	url      string
	accepted chan *websocket.Conn
	// The client's text frames and binary frames, in arrival order.
	text  chan map[string]any
	audio chan []byte
}

func startFakeEngine(t *testing.T) *fakeEngine {
	t.Helper()
	engine := &fakeEngine{
		accepted: make(chan *websocket.Conn, 1),
		text:     make(chan map[string]any, 64),
		audio:    make(chan []byte, 64),
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/voice/session" {
			http.NotFound(w, r)
			return
		}
		conn, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		engine.accepted <- conn
		for {
			kind, data, err := conn.Read(context.Background())
			if err != nil {
				return
			}
			if kind == websocket.MessageBinary {
				engine.audio <- data
				continue
			}
			var frame map[string]any
			if json.Unmarshal(data, &frame) == nil {
				engine.text <- frame
			}
		}
	}))
	t.Cleanup(server.Close)
	engine.url = server.URL
	return engine
}

// engineSide is the engine's end of one session, after its `start_session` arrived.
type engineSide struct {
	t      *testing.T
	engine *fakeEngine
	conn   *websocket.Conn
	start  map[string]any
}

func (e *fakeEngine) session(t *testing.T) *engineSide {
	t.Helper()
	conn := await(t, e.accepted, "the client to open the voice session")
	return &engineSide{t: t, engine: e, conn: conn, start: await(t, e.text, "start_session")}
}

func (s *engineSide) send(frame map[string]any) {
	s.t.Helper()
	text, err := json.Marshal(frame)
	if err != nil {
		s.t.Fatalf("cannot encode an engine frame: %v", err)
	}
	if err := s.conn.Write(context.Background(), websocket.MessageText, text); err != nil {
		s.t.Fatalf("the engine could not send %v: %v", frame["type"], err)
	}
}

func (s *engineSide) sendAudio(pcm []byte) {
	s.t.Helper()
	if err := s.conn.Write(context.Background(), websocket.MessageBinary, pcm); err != nil {
		s.t.Fatalf("the engine could not send audio: %v", err)
	}
}

// play sends one whole play: `play`, its audio in one binary frame, and `play_done`.
func (s *engineSide) play(id string, pcm []byte) {
	s.t.Helper()
	s.send(map[string]any{"type": "play", "id": id, "format": "pcm_16000"})
	s.sendAudio(pcm)
	s.send(map[string]any{"type": "play_done", "id": id})
}

// speakID waits for the client's next `speak` and returns its id.
func (s *engineSide) speakID(text string) string {
	s.t.Helper()
	frame := await(s.t, s.engine.text, "speak")
	if frame["type"] != "speak" || frame["text"] != text {
		s.t.Fatalf("got frame %v, want speak %q", frame, text)
	}
	id, _ := frame["id"].(string)
	if id == "" {
		s.t.Fatalf("speak has no id: %v", frame)
	}
	return id
}

// reportsWhilePlaying stands in for the call's send loop: it pulls frames from the speaker until
// the engine got `count` playback reports, and returns them as "<state> <id>".
func (s *engineSide) reportsWhilePlaying(speaker *callSpeaker, count int) []string {
	s.t.Helper()
	reports := []string{}
	deadline := time.After(engineTestWait)
	for len(reports) < count {
		if _, err := speaker.ReadFrame(); err != nil {
			s.t.Fatalf("the speaker must give a frame on every pull, got %v", err)
		}
		select {
		case frame := <-s.engine.text:
			if frame["type"] != "playback" {
				s.t.Fatalf("got frame %v, want a playback report", frame)
			}
			reports = append(reports, frame["state"].(string)+" "+frame["id"].(string))
		case <-time.After(time.Millisecond):
		case <-deadline:
			s.t.Fatalf("timed out waiting for %d playback reports, got %q", count, reports)
		}
	}
	return reports
}

// sessionUnderTest is a voiceSession that runs against the fake engine.
type sessionUnderTest struct {
	*voiceSession
	peerAudio chan []byte
	turns     chan string
	// What run returned, once the session is over.
	ended chan error
}

func runSession(t *testing.T, baseURL string) *sessionUnderTest {
	t.Helper()
	under := &sessionUnderTest{
		peerAudio: make(chan []byte, peerAudioQueue),
		turns:     make(chan string, 8),
		ended:     make(chan error, 1),
	}
	under.voiceSession = newVoiceSession(func(text string) { under.turns <- text }, func(string, ...any) {})
	ctx, cancel := context.WithCancel(context.Background())
	go func() { under.ended <- under.run(ctx, baseURL, under.peerAudio) }()
	t.Cleanup(func() {
		cancel()
		<-under.done
	})
	return under
}

type sayResult struct {
	line spoken
	err  error
}

// sayAsync runs `say` beside the test, which plays the engine's part while it waits.
func (s *sessionUnderTest) sayAsync(text string) <-chan sayResult {
	result := make(chan sayResult, 1)
	go func() {
		line, err := s.say(text)
		result <- sayResult{line, err}
	}()
	return result
}

func TestVoiceSessionStartsWithTheCallAudioFormats(t *testing.T) {
	engine := startFakeEngine(t)
	runSession(t, engine.url)

	// No `barge_in` field: the engine's own behavior setting decides.
	want := map[string]any{
		"type":     "start_session",
		"client":   "whatsapp-call",
		"audio":    map[string]any{"encoding": "pcm_s16le", "sample_rate": float64(16000), "channels": float64(1)},
		"playback": map[string]any{"delivery": "bytes", "formats": []any{"pcm_16000"}},
	}
	if got := engine.session(t).start; !reflect.DeepEqual(got, want) {
		t.Fatalf("start_session = %v, want %v", got, want)
	}
}

func TestPeerAudioGoesUpAsBinaryFrames(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	engine.session(t)

	first, second := tone(0.1, 1), tone(0.2, 1)
	session.peerAudio <- first
	session.peerAudio <- second

	if got := await(t, engine.audio, "the first peer frame"); !reflect.DeepEqual(got, first) {
		t.Fatal("the first binary frame is not the first peer frame")
	}
	if got := await(t, engine.audio, "the second peer frame"); !reflect.DeepEqual(got, second) {
		t.Fatal("the second binary frame is not the second peer frame")
	}
}

func TestOnlyTurnEndDeliversATurn(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	side := engine.session(t)

	side.send(map[string]any{"type": "state", "value": "listening"})
	side.send(map[string]any{"type": "transcript", "text": "mhm"})
	side.send(map[string]any{"type": "ignored", "text": "mhm", "kind": "backchannel"})
	side.send(map[string]any{"type": "turn_start"})
	side.send(map[string]any{"type": "turn_dropped", "text": "", "kind": nil})
	side.send(map[string]any{"type": "a_frame_from_the_future", "text": "ignore me"})
	side.send(map[string]any{"type": "turn_end", "text": "What is the weather?"})

	if got := await(t, session.turns, "the turn"); got != "What is the weather?" {
		t.Fatalf("turn = %q, want the text of turn_end", got)
	}
	if len(session.turns) != 0 {
		t.Fatal("a frame other than turn_end delivered a turn")
	}
}

func TestSayPlaysItsLineAndReportsStartedThenFinished(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	side := engine.session(t)

	said := session.sayAsync("Hello there.")
	id := side.speakID("Hello there.")
	side.play(id, tone(0.1, 1.5))

	if got := await(t, said, "say to return"); got.err != nil || got.line.status != "speaking" {
		t.Fatalf("say = %+v, want speaking", got)
	}
	want := []string{"started " + id, "finished " + id}
	if got := side.reportsWhilePlaying(session.speaker, 2); !reflect.DeepEqual(got, want) {
		t.Fatalf("playback reports %q, want %q", got, want)
	}
}

func TestSayFailsWithTheEngineMessageWhenItsPlayHasNoAudio(t *testing.T) {
	const message = "elevenlabs: 401 invalid api key"
	for name, errorFirst := range map[string]bool{"error before the play": true, "error after the play": false} {
		t.Run(name, func(t *testing.T) {
			engine := startFakeEngine(t)
			session := runSession(t, engine.url)
			side := engine.session(t)

			said := session.sayAsync("Hello there.")
			id := side.speakID("Hello there.")
			if errorFirst {
				side.send(map[string]any{"type": "error", "message": message})
			}
			side.send(map[string]any{"type": "play", "id": id, "format": "pcm_16000"})
			side.send(map[string]any{"type": "play_done", "id": id})
			if !errorFirst {
				side.send(map[string]any{"type": "error", "message": message})
			}

			got := await(t, said, "say to return")
			if got.err == nil || !strings.Contains(got.err.Error(), message) {
				t.Fatalf("say = %+v, want an error with the engine's message", got)
			}
			report := await(t, engine.text, "the playback report")
			want := map[string]any{"type": "playback", "id": id, "state": "failed"}
			if !reflect.DeepEqual(report, want) {
				t.Fatalf("playback report %v, want %v", report, want)
			}
		})
	}
}

func TestStopPlaybackClearsTheQueue(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	side := engine.session(t)

	saidA := session.sayAsync("First line.")
	a := side.speakID("First line.")
	side.play(a, tone(0.1, 3))
	await(t, saidA, "the first say to return")
	saidB := session.sayAsync("Second line.")
	b := side.speakID("Second line.")
	side.play(b, tone(0.2, 3))
	await(t, saidB, "the second say to return")
	if _, err := session.speaker.ReadFrame(); err != nil {
		t.Fatalf("unexpected error %v", err)
	}
	started := map[string]any{"type": "playback", "id": a, "state": "started"}
	if got := await(t, engine.text, "the first playback report"); !reflect.DeepEqual(got, started) {
		t.Fatalf("playback report %v, want %v", got, started)
	}

	// The engine cuts the first line and drops the second, then a third line arrives. Its say
	// returns after the stop was handled, because the frames are handled in order.
	saidC := session.sayAsync("Third line.")
	c := side.speakID("Third line.")
	side.send(map[string]any{"type": "stop_playback", "id": a, "dropped": []string{b}})
	side.play(c, tone(0.3, 2))
	await(t, saidC, "the third say to return")

	frame, err := session.speaker.ReadFrame()
	if err != nil {
		t.Fatalf("unexpected error %v", err)
	}
	assertLevel(t, "the frame after the stop", frame[0], 0.3)
	want := []string{"started " + c, "finished " + c}
	if got := side.reportsWhilePlaying(session.speaker, 2); !reflect.DeepEqual(got, want) {
		t.Fatalf("playback reports %q, want only the third line: %q", got, want)
	}
}

func TestSayFailsWhenItsLineIsDroppedBeforeItsAudioArrives(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	side := engine.session(t)

	said := session.sayAsync("Hello there.")
	id := side.speakID("Hello there.")
	side.send(map[string]any{"type": "play", "id": id, "format": "pcm_16000"})
	side.send(map[string]any{"type": "stop_playback", "id": nil, "dropped": []string{id}})

	got := await(t, said, "say to return")
	if got.err == nil || !strings.Contains(got.err.Error(), "took the floor") {
		t.Fatalf("say = %+v, want an error that says the line was dropped", got)
	}
}

func TestSayReportsQueuedWhenNoAudioArrivesInTime(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	session.audioWait = 20 * time.Millisecond
	side := engine.session(t)

	said := session.sayAsync("Hello there.")
	side.speakID("Hello there.")

	want := sayResult{line: spoken{status: "queued"}}
	if got := await(t, said, "say to return"); got != want {
		t.Fatalf("say = %+v, want queued", got)
	}
}

func TestQueuedSayCarriesAnEngineErrorThatArrivedAfterItsLine(t *testing.T) {
	const message = "tts is off or has no provider; this session cannot speak"
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	session.audioWait = time.Second
	side := engine.session(t)

	said := session.sayAsync("Hello there.")
	side.speakID("Hello there.")
	side.send(map[string]any{"type": "error", "message": message})

	want := sayResult{line: spoken{status: "queued", engineError: message}}
	if got := await(t, said, "say to return"); got != want {
		t.Fatalf("say = %+v, want queued with the engine's message", got)
	}
}

func TestSayFailsOnceTheEngineEndsTheSession(t *testing.T) {
	engine := startFakeEngine(t)
	session := runSession(t, engine.url)
	side := engine.session(t)

	side.send(map[string]any{"type": "ended", "reason": "stt_failed"})
	if err := await(t, session.ended, "the session to end"); err == nil || !strings.Contains(err.Error(), "stt_failed") {
		t.Fatalf("run returned %v, want the engine's reason", err)
	}

	_, err := session.say("Hello there.")
	if err == nil || !strings.Contains(err.Error(), "voice session of this call is over") || !strings.Contains(err.Error(), "stt_failed") {
		t.Fatalf("say error = %v, want one that says the voice session is over and why", err)
	}
}

func TestSayFailsWhenTheVoiceSessionCannotConnect(t *testing.T) {
	gone := httptest.NewServer(http.NotFoundHandler())
	gone.Close()
	session := runSession(t, gone.URL)

	if err := await(t, session.ended, "the session to end"); err == nil || !strings.Contains(err.Error(), "voice session connect failed") {
		t.Fatalf("run returned %v, want a connect failure", err)
	}
	if _, err := session.say("Hello there."); err == nil || !strings.Contains(err.Error(), "voice session of this call is over") {
		t.Fatalf("say error = %v, want one that says the voice session is over", err)
	}
}
