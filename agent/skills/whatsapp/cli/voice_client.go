package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/coder/websocket"
)

// This is the edge to the voice skill's server, Vesta's one voice backend (STT + TTS providers,
// keys, and the chosen voice). The call bridge holds no provider logic: it hands 16 kHz PCM to
// these functions and gets transcripts and synthesized speech back, so the phone call and the app
// share the exact same voice. The voice server is a sibling daemon in the same container; vestad
// assigns its port, so we resolve it the same idempotent way `register-service` does.

const (
	voiceResolveTimeout = 5 * time.Second
	voiceSynthTimeout   = 60 * time.Second
	sttSendQueue        = 64 // peer frames buffered between the meowcaller sink and the STT socket
)

// insecureVestadClient talks to vestad over its self-signed loopback TLS (fingerprint-pinned
// elsewhere; here the host is always localhost), so certificate verification is skipped by design.
func insecureVestadClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout:   timeout,
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}},
	}
}

// resolveVoiceBaseURL asks vestad for the voice service's port (idempotent: the same POST
// register-service uses, so it never disturbs voice's own registration) and health-checks it, so a
// call only proceeds when the voice backend is actually up. Returns a friendly error otherwise.
// The body omits "public" so vestad keeps the flag voice registered itself with; sending a value
// here would make resolving a port silently rewrite the service's exposure.
func resolveVoiceBaseURL(ctx context.Context) (string, error) {
	vestadPort := os.Getenv("VESTAD_PORT")
	agentName := os.Getenv("AGENT_NAME")
	agentToken := os.Getenv("AGENT_TOKEN")
	if vestadPort == "" || agentName == "" || agentToken == "" {
		return "", fmt.Errorf("cannot reach the voice backend: identity env (VESTAD_PORT/AGENT_NAME/AGENT_TOKEN) is not set")
	}

	url := fmt.Sprintf("https://localhost:%s/agents/%s/services", vestadPort, agentName)
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

// synthesizeSpeech turns text into 16 kHz mono float32 samples via the voice backend's TTS,
// requesting the raw `pcm` format so the bytes drop straight into a call with no decode step.
func synthesizeSpeech(ctx context.Context, baseURL, text string) ([]float32, error) {
	body, err := json.Marshal(map[string]string{"text": text, "format": "pcm"})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/tts/speak", strings.NewReader(string(body)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := (&http.Client{Timeout: voiceSynthTimeout}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("voice TTS request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 500))
		return nil, fmt.Errorf("voice TTS returned %d: %s", resp.StatusCode, string(msg))
	}
	pcm, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	return pcm16ToFloat(pcm), nil
}

// sttTurn is one thing the caller said, finalized at end-of-turn by the voice backend.
type sttTurn struct {
	transcript string
}

// sttEvents carries the decoded output of a live STT session: onSpeechStart fires when the caller
// begins a turn (the cue to stop Vesta talking, natural barge-in), and turns delivers each
// finalized utterance.
type sttEvents struct {
	onSpeechStart func()
	turns         chan sttTurn
}

// streamSTT opens a WebSocket to the voice backend's /stt/listen relay and runs it until ctx is
// cancelled (the call ended) or the socket closes. Peer PCM frames arriving on `frames` are sent
// up as binary; the relay's TurnInfo events are decoded into speech-start cues and finalized
// turns. The backend already fixes linear16 @ 16 kHz, exactly meowcaller's frame format, so no
// audio params are needed on the URL.
func streamSTT(ctx context.Context, baseURL string, frames <-chan []byte, events sttEvents) error {
	wsURL := "ws" + strings.TrimPrefix(baseURL, "http") + "/stt/listen"
	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		return fmt.Errorf("voice STT connect failed: %w", err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")
	conn.SetReadLimit(-1)

	sendErr := make(chan error, 1)
	go func() {
		for {
			select {
			case <-ctx.Done():
				sendErr <- ctx.Err()
				return
			case frame, ok := <-frames:
				if !ok {
					sendErr <- nil
					return
				}
				if err := conn.Write(ctx, websocket.MessageBinary, frame); err != nil {
					sendErr <- err
					return
				}
			}
		}
	}()

	var latest string
	for {
		select {
		case err := <-sendErr:
			return err
		default:
		}
		typ, data, err := conn.Read(ctx)
		if err != nil {
			return err
		}
		if typ != websocket.MessageText {
			continue
		}
		var turnInfo struct {
			Type       string `json:"type"`
			Event      string `json:"event"`
			Transcript string `json:"transcript"`
		}
		if err := json.Unmarshal(data, &turnInfo); err != nil || turnInfo.Type != "TurnInfo" {
			continue
		}
		if turnInfo.Transcript != "" {
			latest = turnInfo.Transcript
		}
		switch turnInfo.Event {
		case "StartOfTurn":
			if events.onSpeechStart != nil {
				events.onSpeechStart()
			}
		case "EndOfTurn":
			if latest != "" {
				select {
				case events.turns <- sttTurn{transcript: latest}:
				case <-ctx.Done():
					return ctx.Err()
				}
				latest = ""
			}
		}
	}
}
