package main

import (
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDetectMediaTypeMimetypes(t *testing.T) {
	cases := map[string]string{
		"photo.jpg":   "image/jpeg",
		"img.png":     "image/png",
		"clip.mp4":    "video/mp4",
		"voice.ogg":   "audio/ogg",
		"audio.wav":   "audio/wav",
		"report.pdf":  "application/pdf",
		"UPPER.PDF":   "application/pdf",
		"doc.doc":     "application/msword",
		"doc.docx":    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"sheet.xls":   "application/vnd.ms-excel",
		"sheet.xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"slides.ppt":  "application/vnd.ms-powerpoint",
		"slides.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
		"notes.txt":   "text/plain",
		"data.csv":    "text/csv",
		"archive.zip": "application/zip",
		"readme.md":   "text/markdown",
		"card.vcf":    "text/vcard",
		"event.ics":   "text/calendar",
		"unknown.xyz": "application/octet-stream",
		"noext":       "application/octet-stream",
	}
	for name, wantMime := range cases {
		if _, gotMime := detectMediaType(name); gotMime != wantMime {
			t.Errorf("detectMediaType(%q) mimetype = %q, want %q", name, gotMime, wantMime)
		}
	}
}

func TestDownloadMediaWithoutChatUsesStoredChat(t *testing.T) {
	store := newTestStore(t)
	if err := store.StoreChat("15551234567@s.whatsapp.net", "Chat", time.Now()); err != nil {
		t.Fatalf("seed chat: %v", err)
	}
	if _, err := store.db.Exec(`INSERT INTO messages (id, chat_jid, media_type, filename, url) VALUES (?, ?, ?, ?, ?)`,
		"MSG1", "15551234567@s.whatsapp.net", MediaTypeDocument, "report.pdf", "https://mmg.whatsapp.net/d/f/x"); err != nil {
		t.Fatalf("seed message: %v", err)
	}
	info, err := store.GetMessageMediaInfo("MSG1", "")
	if err != nil || info.ChatJID != "15551234567@s.whatsapp.net" {
		t.Fatalf("id-only lookup must return the stored chat, got %+v, %v", info, err)
	}

	wac := &WhatsAppClient{store: store}
	_, err = wac.DownloadMedia("UNKNOWN", "", "")
	if err == nil || err.Error() != "--to is required (chat not found for this message id)" {
		t.Errorf("an unknown id without --to must ask for --to, got %v", err)
	}
}

func TestMediaFilename(t *testing.T) {
	for _, tc := range []struct {
		stored, mediaType, wantSuffix string
	}{
		{"report.pdf", MediaTypeDocument, "report.pdf"},
		{"../../etc/passwd", MediaTypeDocument, "passwd"},
		{"", MediaTypeImage, ".jpg"},
		{"", MediaTypeAudio, ".ogg"},
	} {
		got := mediaFilename("MSG1", &MediaInfo{Filename: tc.stored, MediaType: tc.mediaType})
		if !strings.HasSuffix(got, tc.wantSuffix) || strings.Contains(got, "/") {
			t.Errorf("mediaFilename(%q, %q) = %q, want a bare name ending %q", tc.stored, tc.mediaType, got, tc.wantSuffix)
		}
		if tc.stored == "" && !strings.HasPrefix(got, "MSG1_") {
			t.Errorf("fallback name %q must start with the message id", got)
		}
	}
}

func TestMediaSavePathJoinsDirectoryWithFilename(t *testing.T) {
	dir := t.TempDir()
	info := &MediaInfo{Filename: "report.pdf", MediaType: MediaTypeDocument}
	for _, tc := range []struct{ in, want string }{
		{dir, filepath.Join(dir, "report.pdf")},
		{dir + "/", filepath.Join(dir, "report.pdf")},
		{filepath.Join(dir, "out.pdf"), filepath.Join(dir, "out.pdf")},
		{"", filepath.Join("/data", "downloads", "report.pdf")},
	} {
		got, err := mediaSavePath("/data", tc.in, "MSG1", info)
		if err != nil || got != tc.want {
			t.Errorf("mediaSavePath(%q) = %q, %v; want %q", tc.in, got, err, tc.want)
		}
	}
}
