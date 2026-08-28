package main

import "testing"

func TestDetectMediaTypeDocuments(t *testing.T) {
	cases := map[string]string{
		"report.pdf":  "application/pdf",
		"doc.doc":     "application/msword",
		"doc.docx":    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"sheet.xls":   "application/vnd.ms-excel",
		"sheet.xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"slides.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
		"notes.txt":   "text/plain",
		"data.csv":    "text/csv",
		"archive.zip": "application/zip",
		"readme.md":   "text/markdown",
		"card.vcf":    "text/vcard",
		"event.ics":   "text/calendar",
		"unknown.xyz": "application/octet-stream",
	}
	for name, wantMime := range cases {
		if _, gotMime := detectMediaType(name); gotMime != wantMime {
			t.Errorf("detectMediaType(%q) mimetype = %q, want %q", name, gotMime, wantMime)
		}
	}
}

func TestDetectMediaTypeExistingPathsUnchanged(t *testing.T) {
	cases := map[string]string{
		"photo.jpg":  "image/jpeg",
		"img.png":    "image/png",
		"clip.mp4":   "video/mp4",
		"voice.ogg":  "audio/ogg",
		"audio.wav":  "audio/wav",
		"noext":      "application/octet-stream",
		"UPPER.PDF":  "application/pdf", // extension matching is case-insensitive
	}
	for name, wantMime := range cases {
		if _, gotMime := detectMediaType(name); gotMime != wantMime {
			t.Errorf("detectMediaType(%q) mimetype = %q, want %q", name, gotMime, wantMime)
		}
	}
}
