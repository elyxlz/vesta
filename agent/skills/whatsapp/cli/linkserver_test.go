package main

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func testClientWithQR(code string) *WhatsAppClient {
	return &WhatsAppClient{currentQRCode: code, authStatus: AuthStatusQRReady}
}

func TestServeQRPNG(t *testing.T) {
	wac := testClientWithQR("test-qr-payload")
	rec := httptest.NewRecorder()
	wac.linkHTTPHandler(rec, httptest.NewRequest("GET", "/agents/vesta/wa-link/qr.png", nil))
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q, want no-store", got)
	}
	if body := rec.Body.Bytes(); len(body) < 8 || string(body[1:4]) != "PNG" {
		t.Error("response is not a PNG")
	}
}

func TestServeQRPNGWithoutCode(t *testing.T) {
	wac := testClientWithQR("")
	rec := httptest.NewRecorder()
	wac.linkHTTPHandler(rec, httptest.NewRequest("GET", "/qr.png", nil))
	if rec.Code != 404 {
		t.Fatalf("status = %d, want 404 when no live code", rec.Code)
	}
}

func TestServeLinkStatusJSON(t *testing.T) {
	wac := testClientWithQR("code")
	rec := httptest.NewRecorder()
	wac.linkHTTPHandler(rec, httptest.NewRequest("GET", "/link-status.json", nil))
	var status map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &status); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if status["status"] != string(AuthStatusQRReady) {
		t.Errorf("status = %q, want qr_ready", status["status"])
	}
}

func TestServeLinkPage(t *testing.T) {
	wac := testClientWithQR("code")
	rec := httptest.NewRecorder()
	wac.linkHTTPHandler(rec, httptest.NewRequest("GET", "/agents/vesta/wa-link/", nil))
	body := rec.Body.String()
	if !strings.Contains(body, "qr.png") || strings.Contains(body, `"/qr.png`) {
		t.Error("page must reference qr.png RELATIVELY so it works behind the tunnel prefix")
	}
	if !strings.Contains(body, "Linked Devices") {
		t.Error("page must carry the phone-side instruction")
	}
}

// TestClearQRClearsCode proves a finished/abandoned link session leaves no stale
// code for the page to serve (the QR link is single-flighted and self-contained,
// so there is no generation machinery to reason about anymore).
func TestClearQRClearsCode(t *testing.T) {
	wac := &WhatsAppClient{currentQRCode: "code"}
	wac.clearQR()
	wac.authMutex.RLock()
	code := wac.currentQRCode
	wac.authMutex.RUnlock()
	if code != "" {
		t.Error("clearQR must clear the current QR code so nothing serves it")
	}
}
