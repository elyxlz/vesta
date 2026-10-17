package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/google/uuid"
)

// This is the edge to the voice skill's service, which owns the STT and TTS providers, their
// keys, and the chosen voice. A call is one client of its voice engine: one WebSocket,
// `GET /voice/session`, for each call. The call sends the other person's audio and the lines to
// speak, and the engine sends the turns it heard and the audio to play
// (~/agent/skills/voice/PROTOCOL.md is the reference). The voice service is a sibling daemon in
// the same container; vestad assigns its port, so we resolve it the same idempotent way
// `register-service` does.

const (
	voiceResolveTimeout = 5 * time.Second
	// How long `say` waits for the first audio of its line before it reports the line as queued.
	sayAudioWait = 4 * time.Second
	// Peer frames buffered between the meowcaller sink and the socket.
	peerAudioQueue = 64
	// The session's first frame: the mic format the engine accepts, and plays as PCM on the socket.
	startSessionFrame = `{"type":"start_session","client":"whatsapp-call",` +
		`"audio":{"encoding":"pcm_s16le","sample_rate":16000,"channels":1},` +
		`"playback":{"delivery":"bytes","formats":["pcm_16000"]}}`
)

// insecureVestadClient talks to vestad over its self-signed TLS (fingerprint-pinned
// elsewhere), so certificate verification is skipped by design.
func insecureVestadClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout:   timeout,
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}},
	}
}

// resolveVoiceBaseURL asks vestad for the voice service's port (idempotent: registering a name
// again returns its existing port, so it never disturbs voice's own registration) and
// health-checks it, so a call only proceeds when the voice backend is actually up. Returns a
// friendly error otherwise.
// The body omits "public" so vestad keeps the flag voice registered itself with; sending a value
// here would make resolving a port silently rewrite the service's exposure.
func resolveVoiceBaseURL(ctx context.Context) (string, error) {
	vestadPort := os.Getenv("VESTAD_PORT")
	vestadHost := os.Getenv("BOX_HOST")
	agentName := os.Getenv("AGENT_NAME")
	agentToken := os.Getenv("AGENT_TOKEN")
	if vestadPort == "" || vestadHost == "" || agentName == "" || agentToken == "" {
		return "", fmt.Errorf("cannot reach the voice backend: identity env (VESTAD_PORT/BOX_HOST/AGENT_NAME/AGENT_TOKEN) is not set")
	}

	url := fmt.Sprintf("https://%s:%s/agents/%s/services", vestadHost, vestadPort, agentName)
	reqBody := strings.NewReader(`{"name":"voice"}`)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, reqBody)
	if err != nil {
		return "", err
	}
	req.Header.Set("X-Agent-Token", agentToken)
	req.Header.Set("Content-Type", "application/json")

	resp, err := insecureVestadClient(voiceResolveTimeout).Do(req)
	if err != nil {
		return "", fmt.Errorf("cannot reach vestad to find the voice backend: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("vestad returned %d resolving the voice service", resp.StatusCode)
	}
	var parsed struct {
		Port int `json:"port"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil || parsed.Port == 0 {
		return "", fmt.Errorf("could not read the voice service port from vestad")
	}

	baseURL := fmt.Sprintf("http://localhost:%d", parsed.Port)
	if err := voiceHealthy(ctx, baseURL); err != nil {
		return "", fmt.Errorf("voice backend is not running (set it up with the voice skill): %w", err)
	}
	return baseURL, nil
}

func voiceHealthy(ctx context.Context, baseURL string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, baseURL+"/health", nil)
	if err != nil {
		return err
	}
	resp, err := (&http.Client{Timeout: voiceResolveTimeout}).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("health check returned %d", resp.StatusCode)
	}
	return nil
}

// clientFrame is a text frame that the call sends after `start_session`: `speak {id, text}` or
// `playback {id, state}`.
type clientFrame struct {
	Type  string `json:"type"`
	ID    string `json:"id"`
	Text  string `json:"text,omitempty"`
	State string `json:"state,omitempty"`
}

// engineFrame holds the fields of the engine's text frames that the call acts on. A field that
// a frame type does not carry stays empty.
type engineFrame struct {
	Type    string   `json:"type"`
	ID      string   `json:"id"`
	Text    string   `json:"text"`
	Message string   `json:"message"`
	Reason  string   `json:"reason"`
	Dropped []string `json:"dropped"`
}

// spoken is what `say` learned about its line.
type spoken struct {
	// "speaking": audio of the line arrived, so it plays after the lines before it. "queued": no
	// audio arrived in time, which is what a line held for the other person's turn looks like.
	status string
}

// sayWaiter is one `say` that waits to learn what became of its line.
type sayWaiter struct {
	// nil: audio of the line arrived. An error: the line will not play.
	result chan error
	// The play ended with no audio, and the error frame that says why did not arrive yet.
	empty bool
}

// voiceSession is the call's side of one voice engine session. run holds the socket for the
// life of the call, say sends a line, and speaker is the audio source the call plays.
type voiceSession struct {
	speaker   *callSpeaker
	onTurn    func(text string)
	logf      func(format string, args ...any)
	audioWait time.Duration
	// wake tells the writer that the outbox has frames. done closes when the session is over.
	wake chan struct{}
	done chan struct{}

	mu      sync.Mutex
	outbox  [][]byte
	waiting map[string]*sayWaiter
	// Why the session is over.
	over error
}

// newVoiceSession builds a session that is not connected yet. onTurn gets each finished turn of
// the other person, on the socket reader.
func newVoiceSession(onTurn func(text string), logf func(format string, args ...any)) *voiceSession {
	s := &voiceSession{
		onTurn:    onTurn,
		logf:      logf,
		audioWait: sayAudioWait,
		wake:      make(chan struct{}, 1),
		done:      make(chan struct{}),
		waiting:   map[string]*sayWaiter{},
	}
	s.speaker = &callSpeaker{report: func(id, state string) {
		s.send(clientFrame{Type: "playback", ID: id, State: state})
	}}
	return s
}

// send queues a text frame for the writer. It never blocks, so the call's send loop can report
// playback through it, and a frame queued before the socket is open goes out when it opens.
func (s *voiceSession) send(frame clientFrame) {
	// A struct of strings always encodes.
	text, _ := json.Marshal(frame)
	s.mu.Lock()
	s.outbox = append(s.outbox, text)
	s.mu.Unlock()
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

// run opens the session and holds it until ctx is cancelled (the call ended), the engine ends
// it, or the socket fails. It returns why the session is over, and every `say` after that fails.
func (s *voiceSession) run(ctx context.Context, baseURL string, peerAudio <-chan []byte) error {
	err := s.serve(ctx, baseURL, peerAudio)
	s.mu.Lock()
	s.over = err
	s.mu.Unlock()
	close(s.done)
	return err
}

func (s *voiceSession) serve(ctx context.Context, baseURL string, peerAudio <-chan []byte) error {
	ctx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	wsURL := "ws" + strings.TrimPrefix(baseURL, "http") + "/voice/session"
	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		return fmt.Errorf("voice session connect failed: %w", err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")
	conn.SetReadLimit(-1)
	if err := conn.Write(ctx, websocket.MessageText, []byte(startSessionFrame)); err != nil {
		return err
	}
	// A write that fails ends the reader too, with the write error as the cause.
	go func() { cancel(s.write(ctx, conn, peerAudio)) }()
	err = s.read(ctx, conn)
	if cause := context.Cause(ctx); cause != nil && !errors.Is(cause, context.Canceled) {
		return cause
	}
	return err
}

// write sends the other person's audio as binary frames and the queued text frames in order.
func (s *voiceSession) write(ctx context.Context, conn *websocket.Conn, peerAudio <-chan []byte) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case pcm := <-peerAudio:
			if err := conn.Write(ctx, websocket.MessageBinary, pcm); err != nil {
				return err
			}
		case <-s.wake:
			s.mu.Lock()
			queued := s.outbox
			s.outbox = nil
			s.mu.Unlock()
			for _, text := range queued {
				if err := conn.Write(ctx, websocket.MessageText, text); err != nil {
					return err
				}
			}
		}
	}
}

// read does what each engine frame says until the session ends. Binary frames are the audio of
// the last play that has no `play_done` yet.
func (s *voiceSession) read(ctx context.Context, conn *websocket.Conn) error {
	receiving := ""
	for {
		kind, data, err := conn.Read(ctx)
		if err != nil {
			return err
		}
		if kind == websocket.MessageBinary {
			if s.speaker.feed(data) {
				s.settle(receiving, nil)
			}
			continue
		}
		var frame engineFrame
		if err := json.Unmarshal(data, &frame); err != nil {
			continue
		}
		switch frame.Type {
		case "turn_end":
			s.onTurn(frame.Text)
		case "play":
			receiving = frame.ID
			s.speaker.begin(frame.ID)
		case "play_done":
			receiving = ""
			if s.speaker.end(frame.ID) {
				s.madeNoAudio(frame.ID)
			}
		case "pause_playback":
			s.speaker.pause()
		case "resume_playback":
			s.speaker.resume()
		case "stop_playback":
			receiving = ""
			s.speaker.stop()
			for _, id := range frame.Dropped {
				s.settle(id, errors.New("the other person took the floor before this line played, so the voice service dropped it; hear their turn, then speak again"))
			}
		case "error":
			s.logf("call voice session: the voice engine reported: %s", frame.Message)
			// An error with an id is about that line alone: it will not play.
			if frame.ID != "" {
				s.settle(frame.ID, noAudioError(frame.Message))
			}
		case "ended":
			return fmt.Errorf("the voice engine ended the session: %s", frame.Reason)
		}
	}
}

// settle gives the `say` that waits on this line its result. A line with no waiter is a no-op.
func (s *voiceSession) settle(id string, result error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if waiter, waits := s.waiting[id]; waits {
		delete(s.waiting, id)
		waiter.result <- result
	}
}

func noAudioError(message string) error {
	return fmt.Errorf("the voice service made no audio for this line: %s", message)
}

// madeNoAudio marks the `say` of a play that ended with no audio (a failed synthesis). The
// engine's error frame with this id says why and settles the line; a line whose error frame
// came first is settled already.
func (s *voiceSession) madeNoAudio(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if waiter, waits := s.waiting[id]; waits {
		waiter.empty = true
	}
}

// settled is what `say` reports for the result of its waiter.
func settled(result error) (spoken, error) {
	if result != nil {
		return spoken{}, result
	}
	return spoken{status: "speaking"}, nil
}

// say asks the engine to speak text and waits to learn what became of the line: its audio
// arrived, it will not play, or nothing arrived within audioWait. The engine decides when the
// line plays.
func (s *voiceSession) say(text string) (spoken, error) {
	id := uuid.NewString()
	waiter := &sayWaiter{result: make(chan error, 1)}
	s.mu.Lock()
	s.waiting[id] = waiter
	s.mu.Unlock()
	s.send(clientFrame{Type: "speak", ID: id, Text: text})

	timer := time.NewTimer(s.audioWait)
	defer timer.Stop()
	select {
	case err := <-waiter.result:
		return settled(err)
	case <-timer.C:
	case <-s.done:
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.waiting, id)
	// A result can land between the wait's end and the lock; it still decides the line.
	select {
	case err := <-waiter.result:
		return settled(err)
	default:
	}
	select {
	case <-s.done:
		return spoken{}, fmt.Errorf("the voice session of this call is over (%v), so the call cannot hear or speak; end it with `whatsapp hangup`", s.over)
	default:
	}
	if waiter.empty {
		return spoken{}, errors.New("the voice service made no audio for this line")
	}
	return spoken{status: "queued"}, nil
}
