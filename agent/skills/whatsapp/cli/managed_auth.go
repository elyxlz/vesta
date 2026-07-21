package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// claim's non-error terminal outcomes, surfaced to the agent as a clean status (not
// a raw error): the pool is still filling (no number bound yet, re-run later), the
// assigned number is blocked (banned; re-run to get a fresh one), or the account is
// temporarily restricted (self-clearing; wait, then re-run).
var (
	errPoolFilling = errors.New("the number pool is still filling; no number is bound yet")
	errBlocked     = errors.New("the assigned number is blocked")
	errRestricted  = errors.New("the account is temporarily restricted by whatsapp")
)

// isBlockedState reports whether a pool state means the number is unusable (banned).
// The control plane owns the fresh-number handoff; the agent just re-runs connect.
func isBlockedState(state string) bool {
	return state == "banned" || state == "blocked"
}

// httpError carries a non-2xx pool-API response so callers can branch on the status
// and the machine key. The control plane signals a ban as 403 account_banned and a
// restriction as 409 account_restricted (never as a 200 body), so classifying by the
// status + key is exact where matching an opaque error string would be brittle.
type httpError struct {
	Status int
	Key    string // the {"error": ...} machine key, empty when absent
	Body   string // trimmed response body, for diagnostics
	Method string
	URL    string
}

func (e *httpError) Error() string {
	if e.Body != "" {
		return fmt.Sprintf("%s %s: %d: %s", e.Method, e.URL, e.Status, e.Body)
	}
	return fmt.Sprintf("%s %s: %d", e.Method, e.URL, e.Status)
}

// httpStatus returns the HTTP status of a pool-API error, if it carries one.
func httpStatus(err error) (int, bool) {
	var he *httpError
	if errors.As(err, &he) {
		return he.Status, true
	}
	return 0, false
}

// classifyBlock maps a pool-API error to the agent-facing terminal state it encodes,
// if any: a banned number (403 account_banned) to errBlocked, a temporary restriction
// (409 account_restricted) to errRestricted. Every other error (including a dry-pool
// 409 with no ready account) returns nil so the caller decides in context.
func classifyBlock(err error) error {
	var he *httpError
	if !errors.As(err, &he) {
		return nil
	}
	switch {
	case he.Status == http.StatusForbidden && he.Key == "account_banned":
		return fmt.Errorf("%w: %s", errBlocked, he.Body)
	case he.Status == http.StatusConflict && he.Key == "account_restricted":
		return fmt.Errorf("%w: %s", errRestricted, he.Body)
	}
	return nil
}

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
	// companion unable to decrypt); provision is fast and unaffected.
	controlHTTPTimeout = 180 * time.Second
	// provisionPollMax bounds a queued (dry-pool) provision. At provisionPollInterval
	// this stays well under SocketTimeout so the whole synchronous handshake (claim +
	// pair + link wait) always returns a terminal result within one socket call.
	provisionPollMax = 60
	// proxyLeasePath is the control-plane endpoint that hands the cloud companion a
	// residential proxy lease. It sits outside /integrations/whatsapp, so leaseProxy
	// builds the URL from controlURL directly rather than through call().
	proxyLeasePath = "/integrations/proxy/lease"
)

// provisionPollInterval is a var so tests can shrink it.
var provisionPollInterval = 3 * time.Second

// managedConfig selects between two ways to reach the same pool API:
//   - direct (self-hosted): WHATSAPP_API_URL + WHATSAPP_API_KEY, a per-account key
//     straight to the home box, no vesta.run and no vestad;
//   - cloud (vesta.run tenant): a server-identity token minted from vestad, sent to
//     vesta.run's /api/integrations/whatsapp, which authenticates and forwards to the home box.
//
// Both hit the same native paths (/provision, /pair); only the base URL
// and the credential differ.
type managedConfig struct {
	directURL  string // home box base, e.g. https://<tunnel> (direct mode)
	directKey  string // per-account key (wak_...) for direct mode
	controlURL string // vesta.run control-plane base, e.g. https://vesta.run/api (cloud mode)
	vestadBase string // this box's vestad over the loopback, e.g. https://localhost:<port>
	agentName  string
	agentToken string
	// cloudManaged is the paid-tenant signal: the control plane's cloud-init sets
	// VESTA_CLOUD_CONTROL_URL only on managed VMs and vestad forwards it into the
	// container, so its presence tells a cloud tenant from a plain self-hosted box
	// (whose identity env is otherwise identical).
	cloudManaged bool
	// proxyURL is a bring-your-own egress override (WHATSAPP_PROXY_URL): an explicit
	// http(s)://user:pass@host:port or socks5:// URL the companion egresses through
	// in every mode, taking precedence over the cloud residential lease. Empty on a
	// box that supplies no proxy, which preserves the fail-closed default.
	proxyURL string
}

// loadManagedConfig reads the managed-auth environment (mirrors the account skill).
func loadManagedConfig() managedConfig {
	base := ""
	if port := strings.TrimSpace(os.Getenv("VESTAD_PORT")); port != "" {
		base = "https://localhost:" + port
	}
	return managedConfig{
		directURL:    strings.TrimRight(strings.TrimSpace(os.Getenv("WHATSAPP_API_URL")), "/"),
		directKey:    strings.TrimSpace(os.Getenv("WHATSAPP_API_KEY")),
		controlURL:   strings.TrimRight(envOrDefault("VESTA_CONTROL_URL", "https://vesta.run/api"), "/"),
		vestadBase:   base,
		agentName:    strings.TrimSpace(os.Getenv("AGENT_NAME")),
		agentToken:   strings.TrimSpace(os.Getenv("AGENT_TOKEN")),
		cloudManaged: strings.TrimSpace(os.Getenv("VESTA_CLOUD_CONTROL_URL")) != "",
		proxyURL:     strings.TrimSpace(os.Getenv("WHATSAPP_PROXY_URL")),
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

// defaultWelcomeText is the prefilled opener the wa.me link carries so the user just
// taps and sends (reply-first onboarding): a warm, natural first inbound message.
const defaultWelcomeText = "Hey! It's me, connecting here on WhatsApp."

// welcomeText is the prefilled first message embedded in the surfaced wa.me link,
// overridable via WHATSAPP_WELCOME_TEXT.
func welcomeText() string {
	return envOrDefault("WHATSAPP_WELCOME_TEXT", defaultWelcomeText)
}

// waMeLink builds the click-to-chat URL that gets the USER to message this agent
// FIRST (reply-first onboarding, #10): the agent surfaces the link to its user, the
// user taps and sends, and only then does the agent reply. A managed (fresh) number
// must never cold-initiate, so the first message in any thread has to be inbound.
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

// isHosted reports whether this box can use managed WhatsApp at all: either a direct
// key (self-hosted managed), or a genuine vesta.run cloud tenant. Every agent
// container carries VESTAD_PORT/AGENT_NAME/AGENT_TOKEN, so their presence alone
// cannot tell a paid tenant from a plain self-hosted box. The distinguishing signal
// is cloudManaged (VESTA_CLOUD_CONTROL_URL), which the control plane's cloud-init
// drop-in sets only on managed VMs and vestad forwards into the container. Without
// it, a plain box falls back to the QR strategy instead of dead-ending on a managed
// path whose account-token mint would 404.
func (m *managedAuth) isHosted() bool {
	return m.isDirect() || (m.cfg.cloudManaged && m.cfg.vestadBase != "" && m.cfg.agentName != "" && m.cfg.agentToken != "")
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
	}
	u := fmt.Sprintf("%s/agents/%s/account-token", m.cfg.vestadBase, m.cfg.agentName)
	// A non-cloud-managed box answers 404; do() carries that status + body in the
	// returned error, so the 404 detail surfaces without a separate decode branch.
	if err := m.do(m.vestad, http.MethodPost, u, map[string]string{"X-Agent-Token": m.cfg.agentToken}, map[string]string{}, &out); err != nil {
		return "", fmt.Errorf("mint server-identity token: %w", err)
	}
	if out.Token == "" {
		return "", fmt.Errorf("vestad did not return a server-identity token")
	}
	return out.Token, nil
}

// authorize resolves the pool-API base URL and Authorization header once. Direct
// mode uses the static per-account key; cloud mode mints ONE short-lived
// server-identity token (SERVER_IDENTITY_TTL 10m, comfortably longer than any
// single command's work), so a caller making several requests in a row (claim's
// poll loop) resolves once here and reuses the result rather than minting per call.
func (m *managedAuth) authorize() (base, auth string, err error) {
	if m.isDirect() {
		return m.cfg.directURL, "Bearer " + m.cfg.directKey, nil
	}
	token, err := m.mintToken()
	if err != nil {
		return "", "", err
	}
	return m.cfg.controlURL + "/integrations/whatsapp", "Bearer " + token, nil
}

// usesResidentialProxy reports whether this box must egress through a leased
// residential proxy: a genuine cloud tenant whose companion would otherwise hit
// WhatsApp from a datacenter IP (a ban signal). A direct self-hosted box already
// egresses from the user's residential IP, so it never leases.
func (m *managedAuth) usesResidentialProxy() bool {
	return m.cfg.cloudManaged && !m.isDirect()
}

// leaseProxy fetches a residential proxy lease for the cloud companion, reusing the
// same server-identity token the rest of managed auth mints. A 503 proxy_unconfigured
// surfaces as a clear "not configured" error so the caller fails closed rather than
// connecting to WhatsApp on the bare datacenter IP.
func (m *managedAuth) leaseProxy() (string, error) {
	token, err := m.mintToken()
	if err != nil {
		return "", err
	}
	var out struct {
		URL string `json:"url"`
	}
	headers := map[string]string{"Authorization": "Bearer " + token}
	if err := m.do(m.control, http.MethodPost, m.cfg.controlURL+proxyLeasePath, headers, map[string]string{}, &out); err != nil {
		if status, ok := httpStatus(err); ok && status == http.StatusServiceUnavailable {
			return "", fmt.Errorf("residential proxy not configured on the control plane: %w", err)
		}
		return "", fmt.Errorf("lease residential proxy: %w", err)
	}
	if out.URL == "" {
		return "", fmt.Errorf("control plane returned an empty proxy lease")
	}
	return out.URL, nil
}

// provisionSelf claims (idempotently) a pool number the USER will own on their own
// phone: the control plane reserves it, the user registers it themselves and keeps
// their phone online, then the agent links only as a companion. Distinct from
// provision, where the agent drives a headless primary for its own number.
func (m *managedAuth) provisionSelf() (string, error) {
	var out struct {
		MSISDN string `json:"msisdn"`
		State  string `json:"state"`
	}
	if err := m.call(http.MethodPost, "/byo", map[string]string{}, &out); err != nil {
		return "", fmt.Errorf("reserve a user-owned number: %w", err)
	}
	if out.MSISDN == "" {
		return "", fmt.Errorf("control plane returned no number for the user-owned account")
	}
	return out.MSISDN, nil
}

// selfNumberOTP blocks server-side (up to the pool API deadline) until the SMS
// verification code for the user-owned number arrives, then returns it for the user
// to enter while registering the number in WhatsApp on their own phone.
func (m *managedAuth) selfNumberOTP() (string, error) {
	var out struct {
		Code string `json:"code"`
	}
	if err := m.call(http.MethodGet, "/byo/otp", nil, &out); err != nil {
		return "", fmt.Errorf("fetch the user-owned number verification code: %w", err)
	}
	if out.Code == "" {
		return "", fmt.Errorf("control plane returned an empty verification code")
	}
	return out.Code, nil
}

// call sends one authenticated request to the pool API, resolving the base +
// credential per call. Direct mode hits the home box with the per-account key;
// cloud mode hits vesta.run's /api/integrations/whatsapp with a freshly minted
// server-identity token. Both use the same native paths, so only the base URL and
// the credential differ.
func (m *managedAuth) call(method, path string, body, out any) error {
	base, auth, err := m.authorize()
	if err != nil {
		return err
	}
	return m.callWith(base, auth, method, path, body, out)
}

// callWith sends one request against an already-resolved base + Authorization,
// so a multi-request caller can reuse a single authorize() result.
func (m *managedAuth) callWith(base, auth, method, path string, body, out any) error {
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

// claim POSTs /provision (idempotent) and, while the pool is dry and the number is
// still being set up, re-POSTs the same idempotent /provision until one is bound.
// The caller persists the returned number (into the state store). A dry pool that
// never binds returns errPoolFilling and a banned number returns errBlocked, both
// surfaced to the agent as a clean status rather than a raw error.
func (m *managedAuth) claim() (managedState, error) {
	// Resolve the credential ONCE for the whole poll: a dry-pool claim can make many
	// /provision calls, and re-minting per call would be up to ~61 loopback token
	// mints for one connect (the token easily outlives the poll window).
	base, auth, err := m.authorize()
	if err != nil {
		return managedState{}, err
	}
	// Bound the poll by wall-clock, not iteration count: under pathological
	// control-plane slowness (each /provision taking seconds) a count-based loop
	// could approach the daemon's socket budget and surface a spurious "daemon not
	// answering". The deadline keeps total claim wall-clock under provisionPollMax*
	// provisionPollInterval regardless of per-call latency; a number binding quickly
	// still returns immediately.
	deadline := time.Now().Add(provisionPollMax * provisionPollInterval)
	for {
		var out struct {
			MSISDN string `json:"msisdn"`
		}
		err := m.callWith(base, auth, http.MethodPost, "/provision", map[string]string{}, &out)
		switch {
		case err == nil && out.MSISDN != "":
			return managedState{MSISDN: out.MSISDN, DirectURL: m.cfg.directURL, DirectKey: m.cfg.directKey}, nil
		case err == nil:
			// A 2xx with no number is off-contract; treat it as "still filling" and
			// keep polling rather than returning a bare success.
		default:
			if blocked := classifyBlock(err); blocked != nil {
				return managedState{}, blocked
			}
			// A dry pool answers 409 with no ready account: keep re-POSTing the
			// idempotent /provision until one binds or the deadline elapses. Any
			// other error is a real failure.
			if status, ok := httpStatus(err); !ok || status != http.StatusConflict {
				return managedState{}, fmt.Errorf("provision: %w", err)
			}
		}
		if !time.Now().Before(deadline) {
			return managedState{}, errPoolFilling
		}
		time.Sleep(provisionPollInterval)
	}
}

// reauth mints a fresh pairing code for st.MSISDN and posts it, re-linking the
// same companion. No new number, no OTP, no user action. It decodes /pair's
// {state}: a number banned after linking comes back blocked, surfaced as
// errBlocked so the agent re-runs connect for a fresh number instead of looping
// on the dead one (claim already handles a /provision-side block on the way in).
func (m *managedAuth) reauth(st managedState, pairPhone func(msisdn string) (string, error)) error {
	code, err := pairPhone(st.MSISDN)
	if err != nil {
		return fmt.Errorf("pair phone: %w", err)
	}
	var out struct {
		State string `json:"state"`
	}
	if err := m.call(http.MethodPost, "/pair", map[string]string{"code": code}, &out); err != nil {
		if blocked := classifyBlock(err); blocked != nil {
			return blocked
		}
		return fmt.Errorf("link: %w", err)
	}
	if isBlockedState(out.State) {
		return fmt.Errorf("%w (state %q)", errBlocked, out.State)
	}
	return nil
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
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		var parsed struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(raw, &parsed)
		return &httpError{Status: resp.StatusCode, Key: parsed.Error, Body: strings.TrimSpace(string(raw)), Method: method, URL: u}
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}
