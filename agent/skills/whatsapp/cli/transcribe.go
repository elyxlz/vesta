package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
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

// voiceSttTimeout bounds the `voice-keys transcribe` shellout so a hung provider
// call never wedges the whatsapp daemon's message path.
const voiceSttTimeout = 30 * time.Second

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

// whisperOutputJunk reports whether whisper's output is a silence tag rather than
// a real transcription. whisper.cpp emits bracketed tags ("[Musica]",
// "[BLANK_AUDIO]", "[Musik]", "[tk]") for near-silent or low-content clips
// instead of returning an error, and those would otherwise reach the agent as if
// they were the transcript. Treat empty/whitespace or any single "[...]" tag-only
// result as silence. (arxiv 2501.11378 documents the hallucination mode.)
var tagOnlyRe = regexp.MustCompile(`^\[[^\[\]]+\]\s*$`)

func whisperOutputJunk(text string) bool {
	t := strings.TrimSpace(text)
	return t == "" || tagOnlyRe.MatchString(t)
}

// transcribeViaVoiceStt shells the voice skill's provider-agnostic transcriber.
// A clean exit (STT configured+enabled and the provider answered) yields the
// transcript; any failure (unconfigured, disabled, provider error, command
// absent, timeout) returns an error so the caller falls back to whisper.
func transcribeViaVoiceStt(audioPath string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), voiceSttTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "voice-keys", "transcribe", audioPath)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if runErr := cmd.Run(); runErr != nil {
		return "", parseVoiceSttError(stderr.Bytes(), runErr, ctx.Err() == context.DeadlineExceeded)
	}
	return strings.TrimSpace(stdout.String()), nil
}

// parseVoiceSttError turns a failed `voice-keys transcribe` run into one clear
// error: the structured {error} the command prints on stderr, a timeout, a
// missing command, or a bare exit failure.
func parseVoiceSttError(stderr []byte, runErr error, timedOut bool) error {
	if timedOut {
		return fmt.Errorf("voice STT timed out")
	}
	var resp struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(bytes.TrimSpace(stderr), &resp) == nil && resp.Error != "" {
		return fmt.Errorf("voice STT: %s", resp.Error)
	}
	if errors.Is(runErr, exec.ErrNotFound) {
		return fmt.Errorf("voice-keys not on PATH")
	}
	return fmt.Errorf("voice STT failed: %w", runErr)
}

// transcriptDecision keeps voice STT primary and whisper the fallback. A clean
// STT answer (voiceErr == nil) always wins, even an empty one (genuine silence).
// Otherwise whisper is used: its error propagates, and a junk (silence-tag)
// whisper result is dropped to empty rather than delivered as the transcript.
func transcriptDecision(voiceText string, voiceErr error, whisperText string, whisperErr error) (string, error) {
	if voiceErr == nil {
		return voiceText, nil
	}
	if whisperErr != nil {
		return "", whisperErr
	}
	if whisperOutputJunk(whisperText) {
		return "", nil
	}
	return whisperText, nil
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

	// Primary: the user's configured STT provider, owned by the voice skill.
	voiceText, voiceErr := transcribeViaVoiceStt(path)
	if voiceErr == nil {
		if voiceText != "" {
			wac.logger.Infof("Transcribed audio %s via voice STT: %s", messageID, voiceText)
		}
		return voiceText, nil
	}
	wac.logger.Infof("Voice STT unavailable for %s (%v); falling back to whisper", messageID, voiceErr)

	// Fallback: local whisper.cpp.
	whisperText, whisperErr := transcribeAudioBuiltIn(path)
	text, err := transcriptDecision(voiceText, voiceErr, whisperText, whisperErr)
	if err != nil {
		wac.logger.Warnf("Transcription failed for %s: %v", messageID, err)
		return "", err
	}
	switch {
	case text != "":
		wac.logger.Infof("Transcribed audio %s via whisper: %s", messageID, text)
	case whisperOutputJunk(whisperText):
		wac.logger.Infof("Whisper produced tag-only/silence %q for %s; treating as no speech", whisperText, messageID)
	}
	return text, nil
}
