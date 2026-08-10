package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/ggerganov/whisper.cpp/bindings/go/pkg/whisper"
	wav "github.com/go-audio/wav"
)

var (
	whisperModel     whisper.Model
	whisperModelOnce sync.Once
	whisperModelErr  error

	// whisperProcessMu serializes all use of the whisper C context: model.NewContext
	// hands out a fresh wrapper per call, but every wrapper shares the one underlying
	// C model context, which whisper.cpp does not support calling concurrently.
	whisperProcessMu sync.Mutex
)

// getLanguage returns WHISPER_LANGUAGE when set (a fixed whisper.cpp language
// code, since auto-detection can misread short clips), defaulting to "auto".
func getLanguage() string {
	if l := os.Getenv("WHISPER_LANGUAGE"); l != "" {
		return l
	}
	return "auto"
}

func getModelPath() string {
	if p := os.Getenv("WHISPER_MODEL"); p != "" {
		return p
	}
	// Prefer multilingual models, fall back to english-only
	if _, err := os.Stat(DefaultWhisperModelPath); err == nil {
		return DefaultWhisperModelPath
	}
	fallbacks := []string{
		"/usr/local/share/ggml-small.en.bin",
		"/usr/local/share/ggml-tiny.bin",
		"/usr/local/share/ggml-tiny.en.bin",
	}
	for _, fb := range fallbacks {
		if _, err := os.Stat(fb); err == nil {
			return fb
		}
	}
	return DefaultWhisperModelPath
}

func loadWhisperModel() (whisper.Model, error) {
	whisperModelOnce.Do(func() {
		modelPath := getModelPath()
		whisperModel, whisperModelErr = whisper.New(modelPath)
		if whisperModelErr != nil {
			whisperModelErr = fmt.Errorf("failed to load whisper model at %s (run ~/agent/skills/whatsapp/setup.sh to download it): %w", modelPath, whisperModelErr)
		}
	})
	return whisperModel, whisperModelErr
}

// whisperThreads is the per-transcription thread budget: all of a small box's
// cores, capped at WhisperMaxThreads on a big one.
func whisperThreads(numCPU int) uint {
	return uint(min(numCPU, WhisperMaxThreads))
}

// transcribeAudioBuiltIn transcribes audio using the built-in whisper.cpp bindings.
func transcribeAudioBuiltIn(audioPath string) (string, error) {
	model, err := loadWhisperModel()
	if err != nil {
		return "", err
	}

	// Convert to 16kHz mono WAV using ffmpeg
	wavPath := audioPath + ".wav"
	defer os.Remove(wavPath)

	cmd := exec.Command("ffmpeg", "-i", audioPath, "-ar", "16000", "-ac", "1", "-f", "wav", "-y", wavPath)
	cmd.Stderr = nil
	cmd.Stdout = nil
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("ffmpeg conversion failed: %w", err)
	}

	// Read WAV file
	samples, err := readWAVSamples(wavPath)
	if err != nil {
		return "", fmt.Errorf("failed to read WAV: %w", err)
	}

	// Create context and process
	ctx, err := model.NewContext()
	if err != nil {
		return "", fmt.Errorf("failed to create whisper context: %w", err)
	}

	lang := getLanguage()
	if err := ctx.SetLanguage(lang); err != nil {
		return "", fmt.Errorf("failed to set language to %q: %w", lang, err)
	}

	// Cap compute threads: the binding otherwise gives the context
	// runtime.NumCPU(). Thread count only partitions the matmuls, it is not a
	// decoding parameter, so the transcript is unaffected.
	ctx.SetThreads(whisperThreads(runtime.NumCPU()))

	// Process and segment reads both touch the C model context shared by every
	// context wrapper (see whisperProcessMu).
	whisperProcessMu.Lock()
	defer whisperProcessMu.Unlock()

	if err := ctx.Process(samples, nil, nil, nil); err != nil {
		return "", fmt.Errorf("whisper processing failed: %w", err)
	}

	var parts []string
	for {
		segment, err := ctx.NextSegment()
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", fmt.Errorf("failed to get segment: %w", err)
		}
		parts = append(parts, segment.Text)
	}

	return strings.TrimSpace(strings.Join(parts, "")), nil
}

func readWAVSamples(path string) ([]float32, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	dec := wav.NewDecoder(f)
	if !dec.IsValidFile() {
		return nil, fmt.Errorf("invalid WAV file")
	}

	buf, err := dec.FullPCMBuffer()
	if err != nil {
		return nil, err
	}

	// Convert int samples to float32 [-1.0, 1.0]
	samples := make([]float32, len(buf.Data))
	bitDepth := dec.BitDepth
	maxVal := float32(int(1)<<(bitDepth-1) - 1)
	for i, s := range buf.Data {
		samples[i] = float32(s) / maxVal
	}

	return samples, nil
}

// whisperOutputJunk reports whether whisper's output is a real transcription.
// whisper.cpp emits bracketed tags ("[Musica]", "[BLANK_AUDIO]", "[Musik]",
// "[tk]") for near-silent or low-content clips instead of returning an error,
// and these get delivered to the agent as if they were the transcript. Treat
// empty/whitespace or any single "[...]" tag-only result as silence and fall
// back to Deepgram. (arxiv 2501.11378 documents the hallucination mode.)
var tagOnlyRe = regexp.MustCompile(`^\[[^\[\]]+\]\s*$`)

func whisperOutputJunk(text string) bool {
	t := strings.TrimSpace(text)
	return t == "" || tagOnlyRe.MatchString(t)
}

// transcribeWithDeepgram is the fallback when whisper failed or produced only a
// junk tag. Synchronous POST to Deepgram nova-3, reusing the WHISPER_LANGUAGE
// hint (defaults to auto). The key is read from the voice skill config at
// ~/.voice/voice_config.json (stt.credentials.deepgram.api_key), overridable
// via VOICE_CONFIG_PATH. If no key is configured the fallback returns an error
// and the caller logs it (no crash, no regression vs delivering a junk tag).
func transcribeWithDeepgram(audioPath string) (string, error) {
	key, err := readDeepgramKey()
	if err != nil {
		return "", fmt.Errorf("deepgram key unavailable: %w", err)
	}
	f, err := os.Open(audioPath)
	if err != nil {
		return "", fmt.Errorf("open audio for deepgram: %w", err)
	}
	defer f.Close()

	url := "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true"
	if lang := getLanguage(); lang != "" && lang != "auto" {
		url += "&language=" + lang
	}
	req, err := http.NewRequest("POST", url, f)
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Token "+key)
	req.Header.Set("Content-Type", "audio/*")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("deepgram request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("deepgram HTTP %d: %s", resp.StatusCode, string(body))
	}
	var dg struct {
		Results struct {
			Channels []struct {
				Alternatives []struct {
					Transcript string `json:"transcript"`
				} `json:"alternatives"`
			} `json:"channels"`
		} `json:"results"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&dg); err != nil {
		return "", fmt.Errorf("decode deepgram response: %w", err)
	}
	if len(dg.Results.Channels) == 0 || len(dg.Results.Channels[0].Alternatives) == 0 {
		return "", nil
	}
	return strings.TrimSpace(dg.Results.Channels[0].Alternatives[0].Transcript), nil
}

func readDeepgramKey() (string, error) {
	path := os.Getenv("VOICE_CONFIG_PATH")
	if path == "" {
		path = filepath.Join(os.Getenv("HOME"), ".voice", "voice_config.json")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	var cfg struct {
		STT struct {
			Credentials struct {
				Deepgram struct {
					APIKey string `json:"api_key"`
				} `json:"deepgram"`
			} `json:"credentials"`
		} `json:"stt"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return "", err
	}
	if cfg.STT.Credentials.Deepgram.APIKey == "" {
		return "", fmt.Errorf("no deepgram api_key in %s", path)
	}
	return cfg.STT.Credentials.Deepgram.APIKey, nil
}

// Convenience wrapper used by handleMessage. Returns the transcription text and any error.
func (wac *WhatsAppClient) transcribeAudioMessage(messageID, chatJID string) (string, error) {
	// Download audio to temp file
	tmpFile := filepath.Join(os.TempDir(), fmt.Sprintf("wa_audio_%s.ogg", messageID))
	defer os.Remove(tmpFile)

	path, err := wac.DownloadMedia(messageID, chatJID, tmpFile)
	if err != nil {
		wac.logger.Warnf("Failed to download audio for transcription: %v", err)
		return "", fmt.Errorf("failed to download audio: %w", err)
	}

	text, err := transcribeAudioBuiltIn(path)
	switch {
	case err != nil:
		wac.logger.Warnf("Whisper failed for %s (%v); trying Deepgram fallback", messageID, err)
	case !whisperOutputJunk(text):
		wac.logger.Infof("Transcribed audio %s: %s", messageID, text)
		return text, nil
	default:
		wac.logger.Infof("Whisper produced tag-only/silence %q for %s; trying Deepgram fallback", text, messageID)
	}

	// Fallback (whisper error OR junk like "[Musica]"). `path` is still on disk
	// here; this method's deferred os.Remove runs only on return.
	dgText, dgErr := transcribeWithDeepgram(path)
	if dgErr != nil {
		wac.logger.Warnf("Deepgram fallback failed for %s: %v", messageID, dgErr)
		return "", dgErr
	}
	if dgText != "" {
		wac.logger.Infof("Deepgram transcribed audio %s: %s", messageID, dgText)
	}
	return dgText, nil
}
