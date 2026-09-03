package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// transcribeArgs builds the `transcribe` invocation: the audio file, plus the
// language WHISPER_LANGUAGE pins (auto-detection can misread short clips).
func transcribeArgs(audioPath, language string) []string {
	args := []string{audioPath}
	if language != "" {
		args = append(args, "--language", language)
	}
	return args
}

// runTranscribe shells the voice skill's `transcribe`, which owns provider
// selection and the local whisper fallback: stdout is the transcript, and a
// non-zero exit carries {"error"} on stderr.
func runTranscribe(audioPath string) (string, error) {
	cmd := exec.Command("transcribe", transcribeArgs(audioPath, os.Getenv("WHISPER_LANGUAGE"))...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", transcribeError(stderr.Bytes(), err)
	}
	return strings.TrimSpace(stdout.String()), nil
}

// transcribeError names why `transcribe` did not answer: the command is not
// installed, the structured {error} it printed, or a bare exit failure.
func transcribeError(stderr []byte, runErr error) error {
	if errors.Is(runErr, exec.ErrNotFound) {
		return errors.New("transcribe not on PATH; install it with: uv tool install --editable ~/agent/skills/voice/cli")
	}
	var resp struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(bytes.TrimSpace(stderr), &resp) == nil && resp.Error != "" {
		return fmt.Errorf("transcribe: %s", resp.Error)
	}
	return fmt.Errorf("transcribe failed: %w", runErr)
}

// transcribeAudioMessage downloads a voice note and hands it to `transcribe`.
// An empty transcript is a clean answer (silence), never an error.
func (wac *WhatsAppClient) transcribeAudioMessage(messageID, chatJID string) (string, error) {
	tmpFile := filepath.Join(os.TempDir(), fmt.Sprintf("wa_audio_%s.ogg", messageID))
	defer os.Remove(tmpFile)

	path, err := wac.DownloadMedia(messageID, chatJID, tmpFile)
	if err != nil {
		wac.logger.Warnf("Failed to download audio for transcription: %v", err)
		return "", fmt.Errorf("failed to download audio: %w", err)
	}

	text, err := runTranscribe(path)
	if err != nil {
		wac.logger.Warnf("Transcription failed for %s: %v", messageID, err)
		return "", err
	}
	if text != "" {
		wac.logger.Infof("Transcribed audio %s: %s", messageID, text)
	}
	return text, nil
}
