package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// fakeVestad is a stand-in for this box's vestad: it mints a server-identity
// token for the agent-token tier, exactly like POST /agents/{name}/account-token.
func fakeVestad(t *testing.T, wantAgentToken string) *httptest.Server {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agents/alice/account-token" {
			http.Error(w, "no", http.StatusNotFound)
			return
		}
		if r.Header.Get("X-Agent-Token") != wantAgentToken {
			http.Error(w, `{"error":"bad agent token"}`, http.StatusUnauthorized)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"token": "sit_minted"})
	}))
	t.Cleanup(srv.Close)
	return srv
}

// managedFor wires a managedAuth against a fake vestad + a control-plane handler.
func managedFor(t *testing.T, control http.HandlerFunc) *managedAuth {
	t.Helper()
	vestad := fakeVestad(t, "atok")
	ctrl := httptest.NewServer(control)
	t.Cleanup(ctrl.Close)
	m := newManagedAuth(managedConfig{
		controlURL: ctrl.URL,
		vestadBase: vestad.URL,
		agentName:  "alice",
		agentToken: "atok",
	})
	return m
}

func TestProvision_claimsPairsAndSaves(t *testing.T) {
	var gotAuth, gotCode string
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/integrations/whatsapp/provision":
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": "+447700900001", "state": "linked"})
		case "/integrations/whatsapp/pair":
			gotAuth = r.Header.Get("Authorization")
			var b map[string]string
			_ = json.NewDecoder(r.Body).Decode(&b)
			gotCode = b["code"]
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "linked"})
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	})

	var paired string
	st, err := m.provision(func(msisdn string) (string, error) {
		paired = msisdn
		return "WXYZ-7788", nil
	})
	if err != nil {
		t.Fatalf("provision: %v", err)
	}
	if paired != "+447700900001" {
		t.Fatalf("pairPhone got msisdn %q", paired)
	}
	if gotCode != "WXYZ-7788" {
		t.Fatalf("posted code = %q", gotCode)
	}
	// The Worker authenticates with the vestad-minted server-identity token.
	if gotAuth != "Bearer sit_minted" {
		t.Fatalf("pair Authorization = %q, want the minted server-identity token", gotAuth)
	}
	// provision returns the number; the linker persists it into the state store.
	if st.MSISDN != "+447700900001" {
		t.Fatalf("provision returned msisdn %q", st.MSISDN)
	}
}

// A queued provision (dry pool) re-POSTs the idempotent /provision until a number
// is bound; the removed GET /session is never called.
func TestProvision_queuedThenBound(t *testing.T) {
	old := provisionPollInterval
	provisionPollInterval = time.Millisecond
	defer func() { provisionPollInterval = old }()

	var provisions int32
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/integrations/whatsapp/provision":
			msisdn := ""
			if atomic.AddInt32(&provisions, 1) >= 3 {
				msisdn = "+447700900002"
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": msisdn, "state": "queued"})
		case "/integrations/whatsapp/pair":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "linked"})
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	})

	st, err := m.provision(func(string) (string, error) { return "C0DE", nil })
	if err != nil {
		t.Fatalf("provision: %v", err)
	}
	if st.MSISDN != "+447700900002" {
		t.Fatalf("queued provision not fulfilled: %+v", st)
	}
}

// A pool that never binds within the poll budget surfaces errPoolFilling.
func TestProvision_dryPoolSurfacesErrPoolFilling(t *testing.T) {
	old := provisionPollInterval
	provisionPollInterval = time.Microsecond
	defer func() { provisionPollInterval = old }()

	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/integrations/whatsapp/provision" {
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": "", "state": "queued"})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	})

	_, err := m.provision(func(string) (string, error) { return "C0DE", nil })
	if !errors.Is(err, errPoolFilling) {
		t.Fatalf("dry-pool provision = %v, want errPoolFilling", err)
	}
}

// A control plane where every /provision is slow must still bound the claim by
// wall-clock, not iteration count: the poll stops near provisionPollMax*
// provisionPollInterval regardless of per-call latency, so the synchronous
// handshake never approaches the daemon's socket budget with a spurious timeout.
func TestClaim_boundsPollByWallClock(t *testing.T) {
	old := provisionPollInterval
	provisionPollInterval = 2 * time.Millisecond
	defer func() { provisionPollInterval = old }()

	const perCallDelay = 20 * time.Millisecond
	var calls int32
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/integrations/whatsapp/provision" {
			atomic.AddInt32(&calls, 1)
			time.Sleep(perCallDelay)
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": "", "state": "queued"})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	})

	start := time.Now()
	_, err := m.claim()
	elapsed := time.Since(start)

	if !errors.Is(err, errPoolFilling) {
		t.Fatalf("slow dry-pool claim = %v, want errPoolFilling", err)
	}
	// A count-based loop would make provisionPollMax+1 slow calls; the wall-clock
	// bound consumes its budget in far fewer, finishing well under that count time.
	if n := atomic.LoadInt32(&calls); n >= provisionPollMax {
		t.Fatalf("claim made %d calls; the wall-clock bound must stop well under %d", n, provisionPollMax)
	}
	if countBound := time.Duration(provisionPollMax+1) * perCallDelay; elapsed >= countBound {
		t.Fatalf("claim took %s; a wall-clock bound must finish well under the count-based %s", elapsed, countBound)
	}
}

// A direct (self-hosted) box uses its own per-account key straight to the home
// box's native paths, with no vestad token and no vesta.run in the loop.
func TestProvision_directKeyHitsHomeBoxNatively(t *testing.T) {
	var gotAuth, provisionPath, pairPath string
	box := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/provision":
			provisionPath, gotAuth = r.URL.Path, r.Header.Get("Authorization")
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": "+447700900003", "state": "pending"})
		case "/pair":
			pairPath = r.URL.Path
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "linked"})
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	}))
	t.Cleanup(box.Close)
	m := newManagedAuth(managedConfig{directURL: box.URL, directKey: "wak_test"})

	if !m.isDirect() || !m.isHosted() {
		t.Fatal("a box with a direct key is direct + hosted")
	}
	st, err := m.provision(func(string) (string, error) { return "K0DE", nil })
	if err != nil {
		t.Fatalf("direct provision: %v", err)
	}
	if st.MSISDN != "+447700900003" {
		t.Fatalf("msisdn = %q", st.MSISDN)
	}
	if provisionPath != "/provision" || pairPath != "/pair" {
		t.Fatalf("direct mode must hit native paths, got provision=%q pair=%q", provisionPath, pairPath)
	}
	if gotAuth != "Bearer wak_test" {
		t.Fatalf("direct mode must send the per-account key, got %q", gotAuth)
	}
}

func TestReauth_postsFreshCode(t *testing.T) {
	var gotCode string
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/integrations/whatsapp/pair" {
			var b map[string]string
			_ = json.NewDecoder(r.Body).Decode(&b)
			gotCode = b["code"]
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "linked"})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	})

	err := m.reauth(managedState{MSISDN: "+44"}, func(string) (string, error) { return "FRSH-0001", nil })
	if err != nil {
		t.Fatalf("reauth: %v", err)
	}
	if gotCode != "FRSH-0001" {
		t.Fatalf("reauth code = %q", gotCode)
	}
}

// A number banned AFTER linking comes back as a blocked /pair state; reauth must
// surface errBlocked so the agent re-runs connect for a fresh number instead of
// looping on the dead one.
func TestReauth_blockedPairStateSurfacesErrBlocked(t *testing.T) {
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/integrations/whatsapp/pair" {
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "banned"})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	})

	err := m.reauth(managedState{MSISDN: "+44"}, func(string) (string, error) { return "FRSH-0001", nil })
	if !errors.Is(err, errBlocked) {
		t.Fatalf("reauth onto a post-link-banned number = %v, want errBlocked", err)
	}
}

// After a post-link ban the control plane auto-heals the account onto a FRESH
// number on the next /provision; provision (which reauth now routes through) must
// pair THAT healed number, not the stale one.
func TestProvision_picksUpHealedNumber(t *testing.T) {
	var paired string
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/integrations/whatsapp/provision":
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": "+447700900099", "state": "linked"})
		case "/integrations/whatsapp/pair":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "linked"})
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	})

	st, err := m.provision(func(msisdn string) (string, error) { paired = msisdn; return "C0DE", nil })
	if err != nil {
		t.Fatalf("provision: %v", err)
	}
	if paired != "+447700900099" || st.MSISDN != "+447700900099" {
		t.Fatalf("must pair the /provision (healed) number, paired=%q st=%q", paired, st.MSISDN)
	}
}

// The pool API signals a ban as an HTTP 403 account_banned, never as a 200 body, so
// claim must map the typed error (not a decoded {state}) to errBlocked. A prior shape
// of this test faked a 200 the server never sends, hiding the mismatch.
func TestClaim_banned403SurfacesErrBlocked(t *testing.T) {
	m := managedFor(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": "account_banned", "detail": "banned"})
	})
	if _, err := m.claim(); !errors.Is(err, errBlocked) {
		t.Fatalf("claim on a 403 account_banned = %v, want errBlocked", err)
	}
}

// A temporary restriction is a distinct HTTP 409 account_restricted (self-clearing);
// claim surfaces it as errRestricted so the agent waits rather than burning attempts.
func TestClaim_restricted409SurfacesErrRestricted(t *testing.T) {
	m := managedFor(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusConflict)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": "account_restricted", "detail": "restricted"})
	})
	if _, err := m.claim(); !errors.Is(err, errRestricted) {
		t.Fatalf("claim on a 409 account_restricted = %v, want errRestricted", err)
	}
}

// A dry pool answers 409 with no ready account (no machine key), distinct from a
// restriction: claim re-POSTs the idempotent /provision until the deadline, then
// returns errPoolFilling (the clean "provisioning" status), never a raw error.
func TestClaim_dryPool409PollsToPoolFilling(t *testing.T) {
	prev := provisionPollInterval
	provisionPollInterval = time.Millisecond
	t.Cleanup(func() { provisionPollInterval = prev })
	var calls atomic.Int32
	m := managedFor(t, func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusConflict)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": "no ready account"})
	})
	if _, err := m.claim(); !errors.Is(err, errPoolFilling) {
		t.Fatalf("claim on a persistently dry pool = %v, want errPoolFilling", err)
	}
	if calls.Load() < 2 {
		t.Fatalf("a dry pool must be re-polled, got %d calls", calls.Load())
	}
}

// A number banned AFTER linking comes back as a 403 on /pair (the error path, not a
// 200 {state}); reauth must map that typed error to errBlocked too.
func TestReauth_banned403SurfacesErrBlocked(t *testing.T) {
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/integrations/whatsapp/pair" {
			w.WriteHeader(http.StatusForbidden)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "account_banned"})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	})
	err := m.reauth(managedState{MSISDN: "+44"}, func(string) (string, error) { return "FRSH-0001", nil })
	if !errors.Is(err, errBlocked) {
		t.Fatalf("reauth on a 403 account_banned = %v, want errBlocked", err)
	}
}

func TestControlError_surfaces(t *testing.T) {
	m := managedFor(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"error":"membership_inactive"}`, http.StatusForbidden)
	})
	if _, err := m.provision(func(string) (string, error) { return "C", nil }); err == nil {
		t.Fatal("expected error on 403")
	}
}

func TestMintToken_missingCredentials(t *testing.T) {
	// No AGENT_TOKEN: the agent cannot authenticate to vestad, so provision fails
	// clearly rather than emitting a transport error.
	m := newManagedAuth(managedConfig{controlURL: "https://x", vestadBase: "https://localhost:1", agentName: "alice"})
	if _, err := m.mintToken(); err == nil {
		t.Fatal("expected error without AGENT_TOKEN")
	}
	// Not in an agent container at all.
	m2 := newManagedAuth(managedConfig{controlURL: "https://x"})
	if _, err := m2.mintToken(); err == nil {
		t.Fatal("expected error without VESTAD_PORT/AGENT_NAME")
	}
}

func TestWaMeLink(t *testing.T) {
	st := managedState{MSISDN: "+39 351 152 6318"}
	got := waMeLink(st.MSISDN, "hi there")
	want := "https://wa.me/393511526318?text=hi+there"
	if got != want {
		t.Errorf("WaMeLink = %q, want %q", got, want)
	}
	if l := waMeLink("393511526318", ""); l != "https://wa.me/393511526318" {
		t.Errorf("waMeLink no-text = %q", l)
	}
}
