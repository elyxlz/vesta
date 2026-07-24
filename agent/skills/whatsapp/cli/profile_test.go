package main

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"testing"
)

func pngBytes(t *testing.T) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, 8, 8))
	img.Set(0, 0, color.RGBA{R: 10, G: 20, B: 30, A: 255})
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatalf("encode png: %v", err)
	}
	return buf.Bytes()
}

func jpegBytes(t *testing.T) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, 8, 8))
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, nil); err != nil {
		t.Fatalf("encode jpeg: %v", err)
	}
	return buf.Bytes()
}

func TestNormalizeToJPEGPassesJPEGThrough(t *testing.T) {
	in := jpegBytes(t)
	out, err := normalizeToJPEG(in)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !bytes.Equal(in, out) {
		t.Fatalf("JPEG input should be returned unchanged")
	}
}

func TestNormalizeToJPEGConvertsPNG(t *testing.T) {
	out, err := normalizeToJPEG(pngBytes(t))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(out) < 3 || out[0] != 0xFF || out[1] != 0xD8 || out[2] != 0xFF {
		t.Fatalf("output is not JPEG (magic bytes missing)")
	}
	if _, format, err := image.DecodeConfig(bytes.NewReader(out)); err != nil || format != "jpeg" {
		t.Fatalf("output does not decode as jpeg: format=%q err=%v", format, err)
	}
}

func TestNormalizeToJPEGRejectsEmpty(t *testing.T) {
	if _, err := normalizeToJPEG(nil); err == nil {
		t.Fatalf("expected error for empty input")
	}
}

func TestNormalizeToJPEGRejectsNonImage(t *testing.T) {
	if _, err := normalizeToJPEG([]byte("this is not an image")); err == nil {
		t.Fatalf("expected error for non-image input")
	}
}
