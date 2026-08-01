package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"time"
)

// A one-time SMS code on a temporary number, for verifying any service (a signup or a
// 2FA step): the agent reserves a number, uses it on the service, polls for the texted
// code, then releases the number. Two paths reach the same Switchboard pool. Cloud
// (managed) mints a short-lived server-identity token from this box's vestad (loopback,
// agent-token authed; no standing credential) and Bearers it to vesta.run's
// /api/integrations/switchboard/*. Direct (self-hosted) sends an sbk_ key straight to a
// Switchboard base URL; only the base URL, credential, and paths differ.

const (
	httpTimeout    = 30 * time.Second
	controlTimeout = 60 * time.Second
)

// Non-error terminal outcomes of reserve, surfaced to the agent as a clean status
// rather than a raw error: the per-account OTP quota is spent (wait, do not retry),
// or the pool has no free number right now (retry later or pick another country).
var (
	errQuotaExceeded = errors.New("otp_quota_exceeded")
	errOutOfStock    = errors.New("out_of_stock")
)

// errStillPending marks a code poll that reached its deadline with no code yet: not
// a failure, the caller re-runs later with --since set to the last check.
var errStillPending = errors.New("code still pending")

// codePollInterval and codePollMax bound how long `otp code` waits for the SMS to
// land. Vars so tests can shrink them.
var (
	codePollInterval = 3 * time.Second
	codePollMax      = 40 // deadline = codePollMax * codePollInterval
)

// httpError carries a non-2xx Switchboard response so callers branch on the status
// and the machine key. Quota is 429 otp_quota_exceeded and an empty pool is 503
// out_of_stock, so classifying by status + key is exact where matching an opaque
// error string would be brittle.
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

// classifyReserve maps a reserve error to the agent-facing terminal state it
// encodes, if any: 429 otp_quota_exceeded to errQuotaExceeded, 503 out_of_stock to
// errOutOfStock. Every other error returns nil so the caller reports it as-is.
func classifyReserve(err error) error {
	var he *httpError
	if !errors.As(err, &he) {
		return nil
	}
	switch {
	case he.Status == http.StatusTooManyRequests:
		return errQuotaExceeded
	case he.Status == http.StatusServiceUnavailable:
		return errOutOfStock
	}
	return nil
}

// config selects between the two ways to reach the same Switchboard pool:
//   - direct (self-hosted): SWITCHBOARD_API_URL + SWITCHBOARD_API_KEY, an sbk_ key
//     straight to a Switchboard base URL, no vesta.run and no vestad;
//   - cloud (vesta.run tenant): a server-identity token minted from vestad, sent to
//     vesta.run's /api/integrations/switchboard, which authenticates and forwards.
type config struct {
	directURL  string // Switchboard base, e.g. https://<box> (direct mode)
	directKey  string // sbk_ key for direct mode
	vestadBase string // this box's vestad, https://$BOX_HOST:$VESTAD_PORT
	agentName  string
	agentToken string
	// cloudManaged is the paid-tenant signal: cloud-init sets VESTA_CLOUD_CONTROL_URL
	// only on managed VMs and vestad forwards it into the container, so its presence
	// tells a cloud tenant from a plain self-hosted box (whose identity env is
	// otherwise identical).
	cloudManaged bool
	configError  string
}

// loadConfig reads the environment (mirrors the whatsapp skill's managed auth).
func loadConfig() config {
	base := ""
	port := strings.TrimSpace(os.Getenv("VESTAD_PORT"))
	host := strings.TrimSpace(os.Getenv("BOX_HOST"))
	if port != "" && host != "" {
		base = "https://" + host + ":" + port
	}
	directURL := strings.TrimSpace(os.Getenv("SWITCHBOARD_API_URL"))
	directKey := strings.TrimSpace(os.Getenv("SWITCHBOARD_API_KEY"))
	configError := ""
	// A key with no base is meaningless. A base alone is allowed: it means "talk to
	// this Switchboard directly, mint me the sbk_ key from the cloud /token endpoint".
	if directKey != "" && directURL == "" {
		configError = "SWITCHBOARD_API_KEY is set without SWITCHBOARD_API_URL"
		directKey = ""
	}
	return config{
		directURL:    strings.TrimRight(directURL, "/"),
		directKey:    directKey,
		vestadBase:   base,
		agentName:    strings.TrimSpace(os.Getenv("AGENT_NAME")),
		agentToken:   strings.TrimSpace(os.Getenv("AGENT_TOKEN")),
		cloudManaged: strings.TrimSpace(os.Getenv("VESTA_CLOUD_CONTROL_URL")) != "",
		configError:  configError,
	}
}

func envOrDefault(name, def string) string {
	if v := strings.TrimSpace(os.Getenv(name)); v != "" {
		return v
	}
	return def
}

type client struct {
	cfg     config
	control *http.Client
}

func newClient(cfg config) *client {
	return &client{
		cfg:     cfg,
		control: &http.Client{Timeout: controlTimeout},
	}
}

// isDirect reports whether a self-hosted sbk_ key is configured: the box talks
// straight to a Switchboard base URL with its own key, no vesta.run, no vestad.
func (c *client) isDirect() bool {
	return c.cfg.directURL != "" && c.cfg.directKey != ""
}

// isHosted reports whether this box can get OTP numbers at all: either a direct
// sbk_ key (self-hosted), or a genuine vesta.run cloud tenant. Every agent
// container carries VESTAD_PORT/AGENT_NAME/AGENT_TOKEN, so their presence alone
// cannot tell a paid tenant from a plain self-hosted box; cloudManaged
// (VESTA_CLOUD_CONTROL_URL) is the distinguishing signal.
func (c *client) isHosted() bool {
	return c.cfg.configError != "" || c.isDirect() || c.cfg.directURL != "" ||
		(c.cfg.cloudManaged && c.cfg.vestadBase != "" && c.cfg.agentName != "" && c.cfg.agentToken != "")
}

// serverToken is the cloud-path credential: a short-lived server-identity token plus
// the control-plane base URL it authenticates against.
type serverToken struct {
	token      string
	controlURL string
}

// mintServerToken is a package var so tests stub the cloud credential without spawning
// a subprocess.
var mintServerToken = vestaCloudToken

// vestaCloudToken shells out to `vesta-cloud token`, the single source of truth for
// minting this box's server-identity token and resolving the control-plane URL. Every
// skill that calls the control plane as the server routes through this one command, so
// the vestad endpoint, the agent-token header, and the control URL live in one place
// and cannot silently diverge across skills. On failure `vesta-cloud token` prints a
// structured {error} on stdout and exits non-zero, which surfaces here verbatim.
func vestaCloudToken() (serverToken, error) {
	out, runErr := exec.Command("vesta-cloud", "token").Output()
	var resp struct {
		Token      string `json:"token"`
		ControlURL string `json:"control_url"`
		Error      string `json:"error"`
	}
	_ = json.Unmarshal(out, &resp)
	if resp.Token != "" && resp.ControlURL != "" {
		return serverToken{token: resp.Token, controlURL: strings.TrimRight(resp.ControlURL, "/")}, nil
	}
	if resp.Error != "" {
		return serverToken{}, fmt.Errorf("mint server-identity token: %s", resp.Error)
	}
	if runErr != nil {
		return serverToken{}, fmt.Errorf("run `vesta-cloud token` (is the vesta-cloud skill installed?): %w", runErr)
	}
	return serverToken{}, fmt.Errorf("`vesta-cloud token` returned no token")
}

// authorize resolves the Switchboard base URL and Authorization header once, plus
// which path family to use. Direct mode uses the static sbk_ key against native
// /leases paths; cloud mode mints one short-lived server-identity token and hits
// vesta.run's forwarded /reserve, /code, /release. A caller making several requests
// (the code poll) resolves once here and reuses the result.
func (c *client) authorize() (base, auth string, direct bool, err error) {
	if c.cfg.configError != "" {
		return "", "", false, errors.New(c.cfg.configError)
	}
	if c.isDirect() {
		return c.cfg.directURL, "Bearer " + c.cfg.directKey, true, nil
	}
	// A base with no key (self-hosted, delegating the key to the cloud): ask the
	// control plane's /token endpoint for a direct Switchboard URL + sbk_ key, then
	// talk to that Switchboard natively.
	if c.cfg.directURL != "" {
		creds, err := c.fetchDirectToken()
		if err != nil {
			return "", "", false, err
		}
		return strings.TrimRight(creds.URL, "/"), "Bearer " + creds.Key, true, nil
	}
	st, err := mintServerToken()
	if err != nil {
		return "", "", false, err
	}
	return st.controlURL + "/integrations/switchboard", "Bearer " + st.token, false, nil
}

type directToken struct {
	URL string `json:"url"`
	Key string `json:"key"`
}

// fetchDirectToken asks the control plane for a direct Switchboard URL + a freshly
// minted sbk_ key (cloud-authed with a server-identity token), for a self-hosted box
// that talks to Switchboard directly rather than through the forwarded API. The key
// is a secret: it stays inside this process and is never printed.
func (c *client) fetchDirectToken() (directToken, error) {
	st, err := mintServerToken()
	if err != nil {
		return directToken{}, err
	}
	var out directToken
	u := st.controlURL + "/integrations/switchboard/token"
	if _, err := c.do(c.control, http.MethodGet, u, map[string]string{"Authorization": "Bearer " + st.token}, nil, &out); err != nil {
		return directToken{}, fmt.Errorf("mint direct switchboard credentials: %w", err)
	}
	if out.URL == "" || out.Key == "" {
		return directToken{}, fmt.Errorf("/token returned no url/key")
	}
	return out, nil
}

type lease struct {
	ID      string `json:"id"`
	Number  string `json:"number"`
	Service string `json:"service"`
}

// reserve claims a temporary number for one service. Cloud mode POSTs the forwarded
// /reserve; direct mode POSTs native /leases. A spent quota comes back errQuotaExceeded
// and an empty pool errOutOfStock, both surfaced as a clean status.
func (c *client) reserve(service, country string) (lease, error) {
	base, auth, direct, err := c.authorize()
	if err != nil {
		return lease{}, err
	}
	path := "/reserve"
	if direct {
		path = "/leases"
	}
	body := map[string]string{"service": service}
	if country != "" {
		body["country"] = country
	}
	var out lease
	if _, err := c.do(c.control, http.MethodPost, base+path, map[string]string{"Authorization": auth}, body, &out); err != nil {
		if terminal := classifyReserve(err); terminal != nil {
			return lease{}, terminal
		}
		return lease{}, fmt.Errorf("reserve: %w", err)
	}
	if out.ID == "" || out.Number == "" {
		return lease{}, fmt.Errorf("reserve returned no id/number")
	}
	return out, nil
}

// pollCode waits for the SMS code to land on the reserved number, re-checking until
// it arrives or the deadline elapses. A 202 means the code has not arrived yet
// (keep polling); a 200 carries it. On the deadline it returns errStillPending so
// the caller re-runs later with --since set to its last check.
func (c *client) pollCode(id, since string) (string, error) {
	base, auth, direct, err := c.authorize()
	if err != nil {
		return "", err
	}
	codePath := base + "/code?id=" + url.QueryEscape(id)
	if direct {
		codePath = base + "/leases/" + url.PathEscape(id) + "/otp"
	}
	if since != "" {
		sep := "&"
		if !strings.Contains(codePath, "?") {
			sep = "?"
		}
		codePath += sep + "since=" + url.QueryEscape(since)
	}
	deadline := time.Now().Add(time.Duration(codePollMax) * codePollInterval)
	for {
		var out struct {
			Code string `json:"code"`
		}
		status, err := c.do(c.control, http.MethodGet, codePath, map[string]string{"Authorization": auth}, nil, &out)
		if err != nil {
			return "", fmt.Errorf("code: %w", err)
		}
		if status == http.StatusOK && out.Code != "" {
			return out.Code, nil
		}
		// 202 (pending), or a 200 that carried no code yet: keep polling.
		if !time.Now().Before(deadline) {
			return "", errStillPending
		}
		time.Sleep(codePollInterval)
	}
}

// release returns the number to the pool. Idempotent on the server side.
func (c *client) release(id string) error {
	base, auth, direct, err := c.authorize()
	if err != nil {
		return err
	}
	if direct {
		_, err = c.do(c.control, http.MethodPost, base+"/leases/"+url.PathEscape(id)+"/release", map[string]string{"Authorization": auth}, map[string]string{}, nil)
	} else {
		_, err = c.do(c.control, http.MethodPost, base+"/release", map[string]string{"Authorization": auth}, map[string]string{"id": id}, nil)
	}
	if err != nil {
		return fmt.Errorf("release: %w", err)
	}
	return nil
}

// do is the single JSON request helper: encodes body, sets headers, decodes a 2xx
// body into out (if non-nil), and turns non-2xx into an httpError. Returns the HTTP
// status so a caller can tell a 200 from a 202.
func (c *client) do(hc *http.Client, method, u string, headers map[string]string, body, out any) (int, error) {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return 0, err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, u, rdr)
	if err != nil {
		return 0, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := hc.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		var parsed struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(raw, &parsed)
		return resp.StatusCode, &httpError{Status: resp.StatusCode, Key: parsed.Error, Body: strings.TrimSpace(string(raw)), Method: method, URL: u}
	}
	if out != nil && resp.StatusCode != http.StatusNoContent {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil && !errors.Is(err, io.EOF) {
			return resp.StatusCode, err
		}
	}
	return resp.StatusCode, nil
}
