package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func ConvertToOpusOgg(inputFile, outputFile string, bitrate string, sampleRate int) (string, error) {
	// Validate input file path for security
	if err := validateFilePath(inputFile); err != nil {
		return "", fmt.Errorf("invalid input file path: %v", err)
	}

	if _, err := os.Stat(inputFile); err != nil {
		return "", fmt.Errorf("input file not found: %s", inputFile)
	}

	if outputFile == "" {
		ext := filepath.Ext(inputFile)
		outputFile = inputFile[:len(inputFile)-len(ext)] + ".ogg"
	} else {
		// Validate output file path if provided
		if err := validateFilePath(outputFile); err != nil {
			return "", fmt.Errorf("invalid output file path: %v", err)
		}
	}

	outputDir := filepath.Dir(outputFile)
	if outputDir != "" && outputDir != "." {
		if err := os.MkdirAll(outputDir, 0755); err != nil {
			return "", fmt.Errorf("failed to create output directory: %v", err)
		}
	}

	cmd := exec.Command(
		"ffmpeg",
		"-i", inputFile,
		"-c:a", "libopus",
		"-b:a", bitrate,
		"-ar", fmt.Sprintf("%d", sampleRate),
		"-application", "voip",
		"-vbr", "on",
		"-compression_level", "10",
		"-frame_duration", "60",
		"-y",
		outputFile,
	)

	if output, err := cmd.CombinedOutput(); err != nil {
		return "", fmt.Errorf("failed to convert audio (likely need to install ffmpeg): %v - %s", err, output)
	}

	return outputFile, nil
}

func ConvertToOpusOggTemp(inputFile string, bitrate string, sampleRate int) (string, error) {
	tempFile, err := os.CreateTemp("", "*.ogg")
	if err != nil {
		return "", fmt.Errorf("failed to create temp file: %v", err)
	}
	tempFile.Close()

	outputFile, err := ConvertToOpusOgg(inputFile, tempFile.Name(), bitrate, sampleRate)
	if err != nil {
		os.Remove(tempFile.Name())
		return "", err
	}

	return outputFile, nil
}
