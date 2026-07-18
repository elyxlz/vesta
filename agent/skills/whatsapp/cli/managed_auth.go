package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Managed WhatsApp auth (the "token" strategy): the agent side of the hosted
// vesta.run proxy. The agent reaches WhatsApp through the control plane, not the
// home phone box directly, minting a short-lived server-identity token from its
// own vestad (loopback, agent-token authed; no standing credential) and calling
// /api/integrations/whatsapp/* with it as a Bearer. Every paid account is entitled to exactly
// ONE number: provision claims it lazily and idempotently, reauth re-posts a
// fresh pairing code for the same account (no new number, no OTP, no user step).
// This file is the HTTP client + on-disk state; daemon wiring lives in MANAGED_AUTH.md.

const (
	managedHTTPTimeout = 30 * time.Second
	// controlHTTPTimeout bounds a call to the pool API. It is generous because
	// /pair blocks server-side while the home box holds the primary online through
	// the just-linked companion's initial sync (a cold primary there leaves the
	// companion unable to decrypt); provision/session are fast and unaffected.
	controlHTTPTimeout = 180 * time.Second
	// provisionPollMax bounds a queued (dry-pool) provision. At provisionPollInterval
	// this stays well under SocketTimeout so the whole synchronous handshake (claim +
	// pair + link wait) always returns a terminal result within one socket call.
	provisionPollMax = 60
)

// provisionPollInterval is a var so tests can shrink it.
var provisionPollInterval = 3 * time.Second

// managedConfig selects between two ways to reach the same pool API:
//   - direct (self-hosted): WHATSAPP_API_URL + WHATSAPP_API_KEY, a per-account key
//     straight to the home box, no vesta.run and no vestad;
//   - cloud (vesta.run tenant): a server-identity token minted from vestad, sent to
//     vesta.run's /api/integrations/whatsapp, which authenticates and forwards to the home box.
//
// Both hit the same native paths (/provision, /pair, /session); only the base URL
// and the credential differ.
type managedConfig struct {
	directURL  string // home box base, e.g. https://<tunnel> (direct mode)
	directKey  string // per-account key (wak_...) for direct mode
	controlURL string // vesta.run control-plane base, e.g. https://vesta.run/api (cloud mode)
	vestadBase string // this box's vestad over the loopback, e.g. https://localhost:<port>
	agentName  string
	agentToken string
}

// loadManagedConfig reads the managed-auth environment (mirrors the account skill).
func loadManagedConfig() managedConfig {
	base := ""
	if port := strings.TrimSpace(os.Getenv("VESTAD_PORT")); port != "" {
		base = "https://localhost:" + port
	}
	return managedConfig{
		directURL:  strings.TrimRight(strings.TrimSpace(os.Getenv("WHATSAPP_API_URL")), "/"),
		directKey:  strings.TrimSpace(os.Getenv("WHATSAPP_API_KEY")),
		controlURL: strings.TrimRight(envOrDefault("VESTA_CONTROL_URL", "https://vesta.run/api"), "/"),
		vestadBase: base,
		agentName:  strings.TrimSpace(os.Getenv("AGENT_NAME")),
		agentToken: strings.TrimSpace(os.Getenv("AGENT_TOKEN")),
	}
}

func envOrDefault(name, def string) string {
	if v := strings.TrimSpace(os.Getenv(name)); v != "" {
		return v
	}
	return def
}

type managedAuth struct {
	cfg     managedConfig
	control *http.Client
	vestad  *http.Client
}

// managedState is the in-memory result of a claim/provision: the assigned number
// plus (carried through) the direct-mode pool creds. The home box owns the session,
// keyed by this box's Vesta account; the agent persists only the number, now folded
// into the consolidated state.json (state.go), not a file of its own.
type managedState struct {
	MSISDN    string
	DirectURL string
	DirectKey string
}

// WaMeLink builds the click-to-chat URL that gets the USER to message this agent
// FIRST (reply-first onboarding, #10): the agent surfaces the link to its user, the
// user taps and sends, and only then does the agent reply. A managed (fresh) number
// must never cold-initiate, so the first message in any thread has to be inbound.
func (s managedState) WaMeLink(text string) string { return waMeLink(s.MSISDN, text) }

func waMeLink(msisdn, text string) string {
	digits := strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, msisdn)
	link := "https://wa.me/" + digits
	if text != "" {
		link += "?text=" + url.QueryEscape(text)
	}
	return link
}

// isDirect reports whether a direct home-box key is configured: the box talks
// straight to the pool API with its own per-account key, no vesta.run, no vestad.
func (m *managedAuth) isDirect() bool {
	return m.cfg.directURL != "" && m.cfg.directKey != ""
}

// isHosted reports whether this box can use managed WhatsApp at all: either a
// direct key (self-hosted) or the vesta.run server-identity path (cloud tenant).
// Neither present means a plain box, which falls back to the QR strategy.
func (m *managedAuth) isHosted() bool {
	return m.isDirect() || (m.cfg.vestadBase != "" && m.cfg.agentName != "" && m.cfg.agentToken != "")
}

// newManagedAuth builds the pool-API HTTP client. Direct-mode cred reconciliation
// (env vs persisted state) is the caller's job (chooseLinker), so this is pure
// transport with no disk access.
func newManagedAuth(cfg managedConfig) *managedAuth {
	return &managedAuth{
		cfg:     cfg,
		control: &http.Client{Timeout: controlHTTPTimeout},
		// vestad serves a self-signed cert on the loopback; the agent is on the
		// same box, so TLS verification adds nothing and would just fail.
		vestad: &http.Client{
			Timeout:   managedHTTPTimeout,
			Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}},
		},
	}
}

// mintToken asks this box's vestad for a short-lived server-identity token
// (agent-token authed). vestad signs it locally from the box api_key, a pure
// crypto operation with no network call, and hands it back.
func (m *managedAuth) mintToken() (string, error) {
	if m.cfg.vestadBase == "" || m.cfg.agentName == "" {
		return "", fmt.Errorf("not running inside an agent container (no VESTAD_PORT/AGENT_NAME)")
	}
	if m.cfg.agentToken == "" {
		return "", fmt.Errorf("missing AGENT_TOKEN, cannot authenticate to vestad")
	}
	var out struct {
		Token string `json:"token"`
		Error string `json:"error"`
	}
	u := fmt.Sprintf("%s/agents/%s/account-token", m.cfg.vestadBase, m.cfg.agentName)
	if err := m.do(m.vestad, http.MethodPost, u, map[string]string{"X-Agent-Token": m.cfg.agentToken}, map[string]string{}, &out); err != nil {
		return "", fmt.Errorf("mint server-identity token: %w", err)
	}
	if out.Token == "" {
		if out.Error != "" {
			// A non-cloud-managed box answers 404 {error}; surface it verbatim.
			return "", fmt.Errorf("vestad: %s", out.Error)
		}
		return "", fmt.Errorf("vestad did not return a server-identity token")
	}
	return out.Token, nil
}

// call sends an authenticated request to the pool API. Direct mode hits the home
// box with the per-account key; cloud mode hits vesta.run's /api/integrations/whatsapp with a
// freshly minted server-identity token. Both use the same native paths, so only
// the base URL and the credential differ.
func (m *managedAuth) call(method, path string, body, out any) error {
	base, auth := m.cfg.directURL, "Bearer "+m.cfg.directKey
	if !m.isDirect() {
		token, err := m.mintToken()
		if err != nil {
			return err
		}
		base, auth = m.cfg.controlURL+"/integrations/whatsapp", "Bearer "+token
	}
	return m.do(m.control, method, base+path, map[string]string{"Authorization": auth}, body, out)
}

// provision claims this account's one WhatsApp number (lazy + idempotent) and
// links the companion. pairPhone is whatsmeow PairPhone(number) (injected so this
// is testable without a live client). On a restart, load the saved state and call
// reauth directly instead.
func (m *managedAuth) provision(pairPhone func(msisdn string) (string, error)) (managedState, error) {
	st, err := m.claim()
	if err != nil {
		return managedState{}, err
	}
	if err := m.reauth(st, pairPhone); err != nil {
		return managedState{}, err
	}
	return st, nil
}

// claim POSTs /provision (idempotent) and, if the pool is dry and the number is
// still being set up, polls status until one is bound. The caller persists the
// returned number (into the state store).
func (m *managedAuth) claim() (managedState, error) {
	var out struct {
		MSISDN string `json:"msisdn"`
		State  string `json:"state"`
	}
	if err := m.call(http.MethodPost, "/provision", map[string]string{}, &out); err != nil {
		return managedState{}, fmt.Errorf("provision: %w", err)
	}
	st := managedState{MSISDN: out.MSISDN, DirectURL: m.cfg.directURL, DirectKey: m.cfg.directKey}
	for i := 0; st.MSISDN == "" && i < provisionPollMax; i++ {
		time.Sleep(provisionPollInterval)
		s, err := m.status()
		if err != nil {
			return managedState{}, fmt.Errorf("poll queued provision: %w", err)
		}
		st.MSISDN = s.MSISDN
	}
	if st.MSISDN == "" {
		return managedState{}, fmt.Errorf("number still being set up after %d polls", provisionPollMax)
	}
	return st, nil
}

// reauth mints a fresh pairing code for the account's number and posts it,
// re-linking the same companion. The skill calls this on a dropped session — no
// new number, no OTP, no user action.
func (m *managedAuth) reauth(st managedState, pairPhone func(msisdn string) (string, error)) error {
	code, err := pairPhone(st.MSISDN)
	if err != nil {
		return fmt.Errorf("pair phone: %w", err)
	}
	if err := m.call(http.MethodPost, "/pair", map[string]string{"code": code}, nil); err != nil {
		return fmt.Errorf("link: %w", err)
	}
	return nil
}

// whatsappStatus is the pool API's GET /session response.
type whatsappStatus struct {
	Provisioned bool   `json:"provisioned"`
	State       string `json:"state"`
	MSISDN      string `json:"msisdn"`
}

func (m *managedAuth) status() (whatsappStatus, error) {
	var out whatsappStatus
	err := m.call(http.MethodGet, "/session", nil, &out)
	return out, err
}

// do is the single JSON request helper: encodes body, sets headers, decodes a
// 2xx body into out (if non-nil), and turns non-2xx into errors.
func (m *managedAuth) do(client *http.Client, method, u string, headers map[string]string, body, out any) error {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, u, rdr)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("%s %s: %s: %s", method, u, resp.Status, strings.TrimSpace(string(msg)))
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}
