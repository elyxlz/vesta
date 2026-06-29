package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Managed WhatsApp auth (the "token" strategy) — the agent side of the
// whatsapp-auth-api (vesta-cloud). Model A: the agent runs its own whatsmeow,
// redeems a birth token for an assigned primary NUMBER + a durable session
// secret, mints a pairing code with whatsmeow PairPhone(number), and posts that
// code to the API, which drives the primary on its rooted phone to accept the
// companion link. The agent then drives that WhatsApp account from its own
// whatsmeow. Reauth re-posts a fresh code to the same session — no new number.
//
// This file is the HTTP client + on-disk state only; wiring into the daemon's
// connect flow is described in MANAGED_AUTH.md.

const (
	managedHTTPTimeout = 30 * time.Second
	redeemPollMax      = 200 // ceiling before giving up on a queued redeem
)

// redeemPollInterval is a var so tests can shrink it.
var redeemPollInterval = 3 * time.Second

type managedAuth struct {
	base      string
	http      *http.Client
	statePath string
}

// managedState is persisted at ~/.whatsapp[/instance]/managed-auth.json so the
// agent can reauth later with just its secret (the birth token is single-use).
type managedState struct {
	Base      string `json:"base"`
	SessionID string `json:"session_id"`
	Secret    string `json:"agent_secret"`
	MSISDN    string `json:"msisdn"`
}

func newManagedAuth(base, dataDir string) *managedAuth {
	return &managedAuth{
		base:      strings.TrimRight(base, "/"),
		http:      &http.Client{Timeout: managedHTTPTimeout},
		statePath: filepath.Join(dataDir, "managed-auth.json"),
	}
}

// redeem spends the birth token for a session and returns the assigned primary
// number (what whatsmeow pairs against) plus the durable secret. If the pool is
// dry the API queues the session (empty msisdn); redeem polls status until a
// number is bound, then persists the state.
func (m *managedAuth) redeem(token string) (managedState, error) {
	var out struct {
		SessionID string `json:"session_id"`
		Secret    string `json:"agent_secret"`
		MSISDN    string `json:"msisdn"`
		State     string `json:"state"`
	}
	if err := m.do(http.MethodPost, "/redeem", "", map[string]string{"token": token}, &out); err != nil {
		return managedState{}, fmt.Errorf("redeem: %w", err)
	}
	st := managedState{Base: m.base, SessionID: out.SessionID, Secret: out.Secret, MSISDN: out.MSISDN}
	for i := 0; st.MSISDN == "" && i < redeemPollMax; i++ {
		time.Sleep(redeemPollInterval)
		s, err := m.status(st)
		if err != nil {
			return managedState{}, fmt.Errorf("poll queued redeem: %w", err)
		}
		st.MSISDN = s.MSISDN
	}
	if st.MSISDN == "" {
		return managedState{}, fmt.Errorf("redeem still queued after %d polls", redeemPollMax)
	}
	if err := m.save(st); err != nil {
		return managedState{}, err
	}
	return st, nil
}

// provision runs the full first-time handshake: redeem the token, then mint a
// pairing code for the assigned number and post it so the API links the
// companion. pairPhone is whatsmeow PairPhone(number) (injected so this is
// testable without a live client). On a restart, load the saved state and call
// reauth directly instead.
func (m *managedAuth) provision(token string, pairPhone func(msisdn string) (string, error)) (managedState, error) {
	st, err := m.redeem(token)
	if err != nil {
		return managedState{}, err
	}
	if err := m.reauth(st, pairPhone); err != nil {
		return managedState{}, err
	}
	return st, nil
}

// reauth mints a fresh pairing code for the session's number and posts it,
// re-linking the same companion. The skill calls this on a dropped session — no
// new number, no OTP, no user action.
func (m *managedAuth) reauth(st managedState, pairPhone func(msisdn string) (string, error)) error {
	code, err := pairPhone(st.MSISDN)
	if err != nil {
		return fmt.Errorf("pair phone: %w", err)
	}
	return m.link(st, code)
}

// link posts a fresh pairing code (from whatsmeow PairPhone) to the session; the
// API drives the primary to accept it. Serves both first link and reauth.
func (m *managedAuth) link(st managedState, code string) error {
	if err := m.do(http.MethodPost, "/sessions/"+st.SessionID+"/pair", st.Secret, map[string]string{"code": code}, nil); err != nil {
		return fmt.Errorf("link: %w", err)
	}
	return nil
}

type sessionStatus struct {
	State  string `json:"state"`
	MSISDN string `json:"msisdn"`
}

func (m *managedAuth) status(st managedState) (sessionStatus, error) {
	var out sessionStatus
	err := m.do(http.MethodGet, "/sessions/"+st.SessionID, st.Secret, nil, &out)
	return out, err
}

func (m *managedAuth) save(st managedState) error {
	b, err := json.MarshalIndent(st, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(m.statePath, b, 0o600); err != nil {
		return fmt.Errorf("save managed-auth state: %w", err)
	}
	return nil
}

// loadManagedState reads a previously-redeemed session for reauth, if present.
func loadManagedState(dataDir string) (managedState, bool) {
	b, err := os.ReadFile(filepath.Join(dataDir, "managed-auth.json"))
	if err != nil {
		return managedState{}, false
	}
	var st managedState
	if json.Unmarshal(b, &st) != nil || st.SessionID == "" || st.Secret == "" {
		return managedState{}, false
	}
	return st, true
}

// do is the single JSON request helper: encodes body, sets the agent secret when
// given, decodes a 2xx body into out (if non-nil), and turns non-2xx into errors.
func (m *managedAuth) do(method, path, secret string, body, out any) error {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, m.base+path, rdr)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if secret != "" {
		req.Header.Set("X-Agent-Secret", secret)
	}
	resp, err := m.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("%s %s: %s: %s", method, path, resp.Status, strings.TrimSpace(string(msg)))
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}
