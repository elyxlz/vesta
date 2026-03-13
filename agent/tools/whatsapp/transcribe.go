package main

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"

	"github.com/ggerganov/whisper.cpp/bindings/go/pkg/whisper"
	wav "github.com/go-audio/wav"
)

const defaultModelPath = "/usr/local/share/ggml-small.en.bin"

var (
	whisperModel   whisper.Model
	whisperModelMu sync.Mutex
)

func getModelPath() string {
	if p := os.Getenv("WHISPER_MODEL"); p != "" {
		return p
	}
	// Try small.en first, fall back to tiny.en
	if _, err := os.Stat(defaultModelPath); err == nil {
		return defaultModelPath
	}
	tiny := "/usr/local/share/ggml-tiny.en.bin"
	if _, err := os.Stat(tiny); err == nil {
		return tiny
	}
	return defaultModelPath
}

func loadWhisperModel() (whisper.Model, error) {
	whisperModelMu.Lock()
	defer whisperModelMu.Unlock()
	if whisperModel != nil {
		return whisperModel, nil
	}
	modelPath := getModelPath()
	model, err := whisper.New(modelPath)
	if err != nil {
		return nil, fmt.Errorf("failed to load whisper model at %s: %w", modelPath, err)
	}
	whisperModel = model
	return whisperModel, nil
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
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("ffmpeg conversion failed: %w: %s", err, stderr.String())
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

	if err := ctx.Process(samples, nil, nil, nil); err != nil {
		return "", fmt.Errorf("whisper processing failed: %w", err)
	}

	// Collect segments
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

// Convenience wrapper used by handleMessage
func (wac *WhatsAppClient) transcribeAudioMessage(messageID, chatJID string) string {
	tmpFile, err := os.CreateTemp("", "wa_audio_*.ogg")
	if err != nil {
		wac.logger.Warnf("Failed to create temp file for transcription: %v", err)
		return ""
	}
	tmpPath := tmpFile.Name()
	tmpFile.Close()
	defer os.Remove(tmpPath)

	path, err := wac.DownloadMedia(messageID, chatJID, tmpPath)
	if err != nil {
		wac.logger.Warnf("Failed to download audio for transcription: %v", err)
		return ""
	}

	text, err := transcribeAudioBuiltIn(path)
	if err != nil {
		wac.logger.Warnf("Transcription failed: %v", err)
		return ""
	}

	if text != "" {
		wac.logger.Infof("Transcribed audio %s: %s", messageID, text)
	}
	return text
}
