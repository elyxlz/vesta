package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestManagedRedeem_immediateAndPersists(t *testing.T) {
	dir := t.TempDir()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && r.URL.Path == "/redeem" {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"session_id": "s1", "agent_secret": "sek", "msisdn": "+447700900001", "state": "pending",
			})
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	}))
	defer srv.Close()

	m := newManagedAuth(srv.URL, dir)
	st, err := m.redeem("tok")
	if err != nil {
		t.Fatalf("redeem: %v", err)
	}
	if st.MSISDN != "+447700900001" || st.Secret != "sek" || st.SessionID != "s1" {
		t.Fatalf("bad state: %+v", st)
	}
	got, ok := loadManagedState(dir)
	if !ok || got.SessionID != "s1" || got.Secret != "sek" {
		t.Fatalf("state not persisted: %+v ok=%v", got, ok)
	}
}

// A queued redeem polls status (with the secret) until a number is bound.
func TestManagedRedeem_queuedThenFulfilled(t *testing.T) {
	old := redeemPollInterval
	redeemPollInterval = time.Millisecond
	defer func() { redeemPollInterval = old }()

	var polls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/redeem":
			_ = json.NewEncoder(w).Encode(map[string]any{"session_id": "s1", "agent_secret": "sek", "msisdn": "", "state": "queued"})
		case "/sessions/s1":
			if r.Header.Get("X-Agent-Secret") != "sek" {
				http.Error(w, "unauth", http.StatusUnauthorized)
				return
			}
			msisdn := ""
			if atomic.AddInt32(&polls, 1) >= 3 {
				msisdn = "+447700900002"
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "pending", "msisdn": msisdn})
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	}))
	defer srv.Close()

	st, err := newManagedAuth(srv.URL, t.TempDir()).redeem("tok")
	if err != nil {
		t.Fatalf("redeem: %v", err)
	}
	if st.MSISDN != "+447700900002" {
		t.Fatalf("queued redeem not fulfilled: %+v", st)
	}
}

func TestManagedLink_postsCodeWithSecret(t *testing.T) {
	var gotCode, gotSecret string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/sessions/s1/pair" {
			gotSecret = r.Header.Get("X-Agent-Secret")
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			gotCode = body["code"]
			w.WriteHeader(http.StatusAccepted)
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	}))
	defer srv.Close()

	err := newManagedAuth(srv.URL, t.TempDir()).link(managedState{SessionID: "s1", Secret: "sek"}, "ABCD-1234")
	if err != nil {
		t.Fatalf("link: %v", err)
	}
	if gotCode != "ABCD-1234" || gotSecret != "sek" {
		t.Fatalf("code/secret not sent: code=%q secret=%q", gotCode, gotSecret)
	}
}

func TestProvision_redeemThenPairThenLink(t *testing.T) {
	var paired, postedCode string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/redeem":
			_ = json.NewEncoder(w).Encode(map[string]any{"session_id": "s1", "agent_secret": "sek", "msisdn": "+447700900003", "state": "pending"})
		case "/sessions/s1/pair":
			if r.Header.Get("X-Agent-Secret") != "sek" {
				http.Error(w, "unauth", http.StatusUnauthorized)
				return
			}
			var b map[string]string
			_ = json.NewDecoder(r.Body).Decode(&b)
			postedCode = b["code"]
			w.WriteHeader(http.StatusAccepted)
		default:
			http.Error(w, "no", http.StatusNotFound)
		}
	}))
	defer srv.Close()

	st, err := newManagedAuth(srv.URL, t.TempDir()).provision("tok", func(msisdn string) (string, error) {
		paired = msisdn
		return "WXYZ-7788", nil
	})
	if err != nil {
		t.Fatalf("provision: %v", err)
	}
	if paired != "+447700900003" {
		t.Fatalf("pairPhone got msisdn %q, want the assigned number", paired)
	}
	if postedCode != "WXYZ-7788" {
		t.Fatalf("posted code = %q", postedCode)
	}
	if st.MSISDN != "+447700900003" || st.Secret != "sek" {
		t.Fatalf("state %+v", st)
	}
}

func TestReauth_freshCodeToSavedSession(t *testing.T) {
	var got string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/sessions/s9/pair" {
			var b map[string]string
			_ = json.NewDecoder(r.Body).Decode(&b)
			got = b["code"]
			w.WriteHeader(http.StatusAccepted)
			return
		}
		http.Error(w, "no", http.StatusNotFound)
	}))
	defer srv.Close()

	err := newManagedAuth(srv.URL, t.TempDir()).reauth(
		managedState{SessionID: "s9", Secret: "x", MSISDN: "+44"},
		func(msisdn string) (string, error) { return "FRSH-0001", nil },
	)
	if err != nil {
		t.Fatalf("reauth: %v", err)
	}
	if got != "FRSH-0001" {
		t.Fatalf("reauth code = %q", got)
	}
}

func TestManagedLink_apiErrorSurfaces(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
	}))
	defer srv.Close()
	if err := newManagedAuth(srv.URL, t.TempDir()).link(managedState{SessionID: "s1", Secret: "x"}, "C"); err == nil {
		t.Fatal("expected error on 401")
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
