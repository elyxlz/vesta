package main

import (
	"fmt"
	"os"
	"path/filepath"
)

// transcribeAudioBuiltIn is stubbed — whisper.cpp not available in this build.
// To enable audio transcription, install whisper.cpp separately (see the whisper skill).
func transcribeAudioBuiltIn(_ string) (string, error) {
	return "", fmt.Errorf("audio transcription not available in this build")
}

// Convenience wrapper used by handleMessage
func (wac *WhatsAppClient) transcribeAudioMessage(messageID, chatJID string) string {
	tmpFile := filepath.Join(os.TempDir(), fmt.Sprintf("wa_audio_%s.ogg", messageID))
	defer os.Remove(tmpFile)

	_, err := wac.DownloadMedia(messageID, chatJID, tmpFile)
	if err != nil {
		wac.logger.Warnf("Failed to download audio for transcription: %v", err)
		return ""
	}

	text, err := transcribeAudioBuiltIn(tmpFile)
	if err != nil {
		wac.logger.Warnf("Transcription not available: %v", err)
		return ""
	}

	return text
}
