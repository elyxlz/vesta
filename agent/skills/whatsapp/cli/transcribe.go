package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
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

	// Auto-detect language (supports Italian, English, etc.)
	if err := ctx.SetLanguage("auto"); err != nil {
		return "", fmt.Errorf("failed to set language to auto: %w", err)
	}

	// The timeout clock starts only once the mutex is held, so each queued voice
	// note gets the full budget. On timeout the goroutine keeps the mutex until
	// Process returns, so a wedged call delays later transcriptions instead of
	// racing them on the shared C context.
	whisperProcessMu.Lock()
	resCh := make(chan whisperResult, 1)
	go func() {
		defer whisperProcessMu.Unlock()
		resCh <- processAndCollect(ctx, samples)
	}()

	select {
	case res := <-resCh:
		return res.text, res.err
	case <-time.After(WhisperProcessTimeout):
		return "", fmt.Errorf("whisper processing timed out after %v", WhisperProcessTimeout)
	}
}

type whisperResult struct {
	text string
	err  error
}

// processAndCollect runs whisper_full and reads back the segments. Both touch the
// shared C model context, so callers must hold whisperProcessMu throughout.
func processAndCollect(ctx whisper.Context, samples []float32) whisperResult {
	if err := ctx.Process(samples, nil, nil, nil); err != nil {
		return whisperResult{err: fmt.Errorf("whisper processing failed: %w", err)}
	}

	var parts []string
	for {
		segment, err := ctx.NextSegment()
		if err == io.EOF {
			break
		}
		if err != nil {
			return whisperResult{err: fmt.Errorf("failed to get segment: %w", err)}
		}
		parts = append(parts, segment.Text)
	}

	return whisperResult{text: strings.TrimSpace(strings.Join(parts, ""))}
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
	if err != nil {
		wac.logger.Warnf("Transcription failed: %v", err)
		return "", err
	}

	if text != "" {
		wac.logger.Infof("Transcribed audio %s: %s", messageID, text)
	}
	return text, nil
}
