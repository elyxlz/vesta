package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// stubServerToken makes authorize()'s cloud path resolve to a fixed credential pointed
// at ctrlURL, standing in for the `vesta-cloud token` subprocess so tests drive the
// control plane directly (no subprocess, no fake vestad).
func stubServerToken(t *testing.T, ctrlURL string) {
	t.Helper()
	prev := mintServerToken
	mintServerToken = func() (serverToken, error) {
		return serverToken{token: "sit_minted", controlURL: ctrlURL}, nil
	}
	t.Cleanup(func() { mintServerToken = prev })
}

// cloudClientFor wires a client against a control-plane handler, with the cloud
// credential stubbed to point at it (forwarded /integrations/switchboard).
func cloudClientFor(t *testing.T, control http.HandlerFunc) *client {
	t.Helper()
	ctrl := httptest.NewServer(control)
	t.Cleanup(ctrl.Close)
	stubServerToken(t, ctrl.URL)
	return newClient(config{vestadBase: "https://vestad.test", agentName: "alice", agentToken: "atok"})
}

// TestParseServerToken pins how a `vesta-cloud token` run maps to a credential or a
// clear error: success, a structured {error} surfaced verbatim, the command missing, a
// timeout, and empty output.
func TestParseServerToken(t *testing.T) {
	if st, err := parseServerToken([]byte(`{"token":"sit","control_url":"https://ctrl/"}`), nil, false); err != nil || st.token != "sit" || st.controlURL != "https://ctrl" {
		t.Fatalf("success = %+v err=%v", st, err)
	}
	if _, err := parseServerToken([]byte(`{"error":"no account linked"}`), errors.New("exit status 3"), false); err == nil || !strings.Contains(err.Error(), "no account linked") {
		t.Fatalf("structured error = %v, want it surfaced verbatim", err)
	}
	notFound := errors.New(`exec: "vesta-cloud": executable file not found in $PATH`)
	if _, err := parseServerToken(nil, notFound, false); err == nil || !strings.Contains(err.Error(), "vesta-cloud skill installed") {
		t.Fatalf("not-installed error = %v, want the install hint", err)
	}
	if _, err := parseServerToken(nil, errors.New("signal: killed"), true); err == nil || !strings.Contains(err.Error(), "timed out") {
		t.Fatalf("timeout error = %v, want a timeout message", err)
	}
}

func TestReserve_cloudMintsTokenAndReturnsNumber(t *testing.T) {
	var gotAuth, gotPath string
	var gotBody map[string]string
	c := cloudClientFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/integrations/switchboard/reserve" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		gotAuth, gotPath = r.Header.Get("Authorization"), r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		_ = json.NewEncoder(w).Encode(map[string]string{"id": "lease_1", "number": "+15550001111", "service": "github"})
	})
	l, err := c.reserve("github", "US")
	if err != nil {
		t.Fatalf("reserve: %v", err)
	}
	if l.ID != "lease_1" || l.Number != "+15550001111" {
		t.Fatalf("reserve returned %+v", l)
	}
	if gotAuth != "Bearer sit_minted" {
		t.Fatalf("reserve Authorization = %q, want the minted server-identity token", gotAuth)
	}
	if gotPath != "/integrations/switchboard/reserve" {
		t.Fatalf("reserve path = %q", gotPath)
	}
	if gotBody["service"] != "github" || gotBody["country"] != "US" {
		t.Fatalf("reserve body = %+v", gotBody)
	}
}

func TestReserve_quota429SurfacesErrQuotaExceeded(t *testing.T) {
	c := cloudClientFor(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": "otp_quota_exceeded"})
	})
	if _, err := c.reserve("github", ""); !errors.Is(err, errQuotaExceeded) {
		t.Fatalf("reserve on 429 = %v, want errQuotaExceeded", err)
	}
}

func TestReserve_outOfStock503SurfacesErrOutOfStock(t *testing.T) {
	c := cloudClientFor(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": "out_of_stock"})
	})
	if _, err := c.reserve("github", ""); !errors.Is(err, errOutOfStock) {
		t.Fatalf("reserve on 503 = %v, want errOutOfStock", err)
	}
}

func TestPollCode_pendingThenCode(t *testing.T) {
	old := codePollInterval
	codePollInterval = time.Millisecond
	t.Cleanup(func() { codePollInterval = old })

	var calls int32
	c := cloudClientFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/integrations/switchboard/code" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		if atomic.AddInt32(&calls, 1) < 3 {
			w.WriteHeader(http.StatusAccepted)
			_ = json.NewEncoder(w).Encode(map[string]string{"status": "pending"})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"code": "123456"})
	})
	code, err := c.pollCode("lease_1", "")
	if err != nil {
		t.Fatalf("pollCode: %v", err)
	}
	if code != "123456" {
		t.Fatalf("pollCode = %q, want 123456", code)
	}
	if atomic.LoadInt32(&calls) < 3 {
		t.Fatalf("a 202 must be re-polled, got %d calls", calls)
	}
}

func TestPollCode_passesIDAndSince(t *testing.T) {
	var gotQuery string
	c := cloudClientFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/integrations/switchboard/code" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		gotQuery = r.URL.RawQuery
		_ = json.NewEncoder(w).Encode(map[string]string{"code": "9"})
	})
	if _, err := c.pollCode("lease_9", "2026-07-31T00:00:00Z"); err != nil {
		t.Fatalf("pollCode: %v", err)
	}
	if !strings.Contains(gotQuery, "id=lease_9") || !strings.Contains(gotQuery, "since=") {
		t.Fatalf("code query = %q, want id + since", gotQuery)
	}
}

func TestPollCode_timesOutStillPending(t *testing.T) {
	oldInterval, oldMax := codePollInterval, codePollMax
	codePollInterval, codePollMax = time.Microsecond, 2
	t.Cleanup(func() { codePollInterval, codePollMax = oldInterval, oldMax })

	c := cloudClientFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/integrations/switchboard/code" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusAccepted)
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "pending"})
	})
	if _, err := c.pollCode("lease_1", ""); !errors.Is(err, errStillPending) {
		t.Fatalf("pollCode past deadline = %v, want errStillPending", err)
	}
}

func TestRelease_cloudPostsID(t *testing.T) {
	var gotPath string
	var gotBody map[string]string
	c := cloudClientFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/integrations/switchboard/release" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		gotPath = r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		_ = json.NewEncoder(w).Encode(map[string]string{})
	})
	if err := c.release("lease_1"); err != nil {
		t.Fatalf("release: %v", err)
	}
	if gotPath != "/integrations/switchboard/release" || gotBody["id"] != "lease_1" {
		t.Fatalf("release path=%q body=%+v", gotPath, gotBody)
	}
}

// A direct (self-hosted) box uses its own sbk_ key straight to the Switchboard base
// URL's native paths (/leases, /leases/{id}/otp, /leases/{id}/release), with no
// vestad token and no vesta.run in the loop.
func TestDirect_sbkKeyHitsNativeLeasePaths(t *testing.T) {
	var reservePath, otpPath, releasePath, gotAuth string
	box := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		switch {
		case r.URL.Path == "/leases" && r.Method == http.MethodPost:
			reservePath = r.URL.Path
			_ = json.NewEncoder(w).Encode(map[string]string{"id": "l7", "number": "+15550002222"})
		case r.URL.Path == "/leases/l7/otp":
			otpPath = r.URL.Path
			_ = json.NewEncoder(w).Encode(map[string]string{"code": "424242"})
		case r.URL.Path == "/leases/l7/release":
			releasePath = r.URL.Path
			_ = json.NewEncoder(w).Encode(map[string]string{})
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	}))
	t.Cleanup(box.Close)
	c := newClient(config{directURL: box.URL, directKey: "sbk_test"})

	if !c.isDirect() || !c.isHosted() {
		t.Fatal("a box with an sbk_ key is direct + hosted")
	}
	l, err := c.reserve("discord", "")
	if err != nil {
		t.Fatalf("direct reserve: %v", err)
	}
	code, err := c.pollCode(l.ID, "")
	if err != nil {
		t.Fatalf("direct pollCode: %v", err)
	}
	if err := c.release(l.ID); err != nil {
		t.Fatalf("direct release: %v", err)
	}
	if reservePath != "/leases" || otpPath != "/leases/l7/otp" || releasePath != "/leases/l7/release" {
		t.Fatalf("direct mode must hit native paths, got reserve=%q otp=%q release=%q", reservePath, otpPath, releasePath)
	}
	if code != "424242" {
		t.Fatalf("direct code = %q", code)
	}
	if gotAuth != "Bearer sbk_test" {
		t.Fatalf("direct mode must send the sbk_ key, got %q", gotAuth)
	}
}

// A self-hosted box with a Switchboard base URL but no key delegates the sbk_ key to
// the cloud: authorize mints it from the /token endpoint (server-identity authed),
// then talks to that Switchboard natively. The key never appears in output.
func TestAuthorize_directCredsFromTokenEndpoint(t *testing.T) {
	var sawTokenAuth string
	ctrl := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/integrations/switchboard/token" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		sawTokenAuth = r.Header.Get("Authorization")
		_ = json.NewEncoder(w).Encode(map[string]string{"url": "https://sb.example", "key": "sbk_minted"})
	}))
	t.Cleanup(ctrl.Close)
	stubServerToken(t, ctrl.URL)
	c := newClient(config{
		directURL: "https://sb.example", // base set, key absent
	})
	base, auth, direct, err := c.authorize()
	if err != nil {
		t.Fatalf("authorize: %v", err)
	}
	if !direct {
		t.Fatal("a /token-minted credential must resolve to direct mode (native paths)")
	}
	if base != "https://sb.example" || auth != "Bearer sbk_minted" {
		t.Fatalf("authorize base=%q auth=%q, want the /token-minted creds", base, auth)
	}
	if sawTokenAuth != "Bearer sit_minted" {
		t.Fatalf("/token Authorization = %q, want the server-identity token", sawTokenAuth)
	}
}

func TestAuthorize_cloudManagedUsesForwardedPath(t *testing.T) {
	c := cloudClientFor(t, func(_ http.ResponseWriter, _ *http.Request) {})
	base, auth, direct, err := c.authorize()
	if err != nil {
		t.Fatalf("authorize: %v", err)
	}
	if direct {
		t.Fatal("a pure cloud tenant must use the forwarded path, not direct")
	}
	if !strings.HasSuffix(base, "/integrations/switchboard") || auth != "Bearer sit_minted" {
		t.Fatalf("cloud authorize base=%q auth=%q", base, auth)
	}
}

func TestLoadConfig_keyWithoutURLIsRejected(t *testing.T) {
	t.Setenv("SWITCHBOARD_API_URL", "")
	t.Setenv("SWITCHBOARD_API_KEY", "sbk_orphan")
	cfg := loadConfig()
	if cfg.configError == "" || cfg.directKey != "" {
		t.Fatalf("a key with no base must be rejected: %+v", cfg)
	}
	if _, err := newClient(cfg).reserve("x", ""); err == nil || !strings.Contains(err.Error(), "without SWITCHBOARD_API_URL") {
		t.Fatalf("reserve with orphan key error = %v", err)
	}
}

func TestLoadConfig_directPairFromEnv(t *testing.T) {
	t.Setenv("SWITCHBOARD_API_URL", "https://sb.example/")
	t.Setenv("SWITCHBOARD_API_KEY", "sbk_env")
	cfg := loadConfig()
	if cfg.directURL != "https://sb.example" || cfg.directKey != "sbk_env" {
		t.Fatalf("loadConfig = url %q key %q", cfg.directURL, cfg.directKey)
	}
}
