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

// A blocked (banned) number surfaces errBlocked so connect can tell the agent to
// re-run for a fresh number rather than emitting a raw error.
func TestProvision_blockedSurfacesErrBlocked(t *testing.T) {
	m := managedFor(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/integrations/whatsapp/provision" {
			_ = json.NewEncoder(w).Encode(map[string]any{"msisdn": "+447700900004", "state": "banned"})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	})

	_, err := m.provision(func(string) (string, error) { return "C0DE", nil })
	if !errors.Is(err, errBlocked) {
		t.Fatalf("provision of a banned number = %v, want errBlocked", err)
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
	got := st.WaMeLink("hi there")
	want := "https://wa.me/393511526318?text=hi+there"
	if got != want {
		t.Errorf("WaMeLink = %q, want %q", got, want)
	}
	if l := waMeLink("393511526318", ""); l != "https://wa.me/393511526318" {
		t.Errorf("waMeLink no-text = %q", l)
	}
}
