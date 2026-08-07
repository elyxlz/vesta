package main

import (
	"bytes"
	"context"
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
// code, then releases the number. Two independent services can supply the number, and
// the agent CHOOSES with --source (the CLI never detects or falls back). `vesta-cloud` is
// Vesta Cloud's OTP service: a short-lived server-identity token from
// `vesta-cloud token` (available on any box whose Vesta Cloud account
// `vesta-cloud whoami` reports), sent Bearer to vesta.run. `switchboard` is a
// Switchboard the owner runs: a static sbk_ key straight at its base URL.

// The two number sources the agent chooses between with --source.
const (
	sourceVestaCloud  = "vesta-cloud"
	sourceSwitchboard = "switchboard"
)

const controlTimeout = 60 * time.Second

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

// config carries the credentials each --source needs:
//   - switchboard: SWITCHBOARD_API_URL + SWITCHBOARD_API_KEY (a static sbk_ key),
//     no vesta.run involved;
//   - vesta-cloud: nothing from here; the credential is a server-identity token minted
//     per call via `vesta-cloud token`. Whether this box holds a Vesta Cloud
//     account is `vesta-cloud whoami`'s answer, never an environment variable;
//     the mint fails with a clear error on a box with no account.
type config struct {
	directURL   string // Switchboard base, e.g. https://<box> (direct mode)
	directKey   string // sbk_ key for direct mode
	configError string
}

// loadConfig reads the environment.
func loadConfig() config {
	directURL := strings.TrimSpace(os.Getenv("SWITCHBOARD_API_URL"))
	directKey := strings.TrimSpace(os.Getenv("SWITCHBOARD_API_KEY"))
	configError := ""
	// Direct mode needs both halves: an operator hands the box an sbk_ key out of
	// band together with the base URL it opens. Either half alone is a misconfiguration.
	switch {
	case directKey != "" && directURL == "":
		configError = "SWITCHBOARD_API_KEY is set without SWITCHBOARD_API_URL"
		directKey = ""
	case directURL != "" && directKey == "":
		configError = "SWITCHBOARD_API_URL is set without SWITCHBOARD_API_KEY"
		directURL = ""
	}
	return config{
		directURL:   strings.TrimRight(directURL, "/"),
		directKey:   directKey,
		configError: configError,
	}
}

type client struct {
	cfg     config
	source  string // sourceVestaCloud | sourceSwitchboard, the agent's --source choice
	control *http.Client
}

func newClient(cfg config, source string) *client {
	return &client{
		cfg:     cfg,
		source:  source,
		control: &http.Client{Timeout: controlTimeout},
	}
}

// isDirect reports whether a static sbk_ key is configured: the box talks
// straight to a Switchboard base URL with its own key, no vesta.run involved.
func (c *client) isDirect() bool {
	return c.cfg.directURL != "" && c.cfg.directKey != ""
}

// serverToken is the Vesta Cloud credential: a short-lived server-identity token plus
// the control-plane base URL it authenticates against.
type serverToken struct {
	token      string
	controlURL string
}

// mintServerToken is a package var so tests stub the Vesta Cloud credential without spawning
// a subprocess.
var mintServerToken = vestaCloudToken

// vestaCloudTokenTimeout bounds the subprocess so a wedged `vesta-cloud token` can never
// hang the CLI's auth path.
const vestaCloudTokenTimeout = 30 * time.Second

// vestaCloudToken shells out to `vesta-cloud token`, the single source of truth for
// minting this box's server-identity token and resolving the control-plane URL. Every
// skill that calls the control plane as the server routes through this one command, so
// the vestad endpoint, the agent-token header, and the control URL live in one place and
// cannot silently diverge across skills.
func vestaCloudToken() (serverToken, error) {
	ctx, cancel := context.WithTimeout(context.Background(), vestaCloudTokenTimeout)
	defer cancel()
	out, runErr := exec.CommandContext(ctx, "vesta-cloud", "token").Output()
	return parseServerToken(out, runErr, ctx.Err() == context.DeadlineExceeded)
}

// parseServerToken turns a `vesta-cloud token` run into a credential or a clear error,
// split from the exec so the failure branches are unit tested. On failure the CLI prints
// a structured {error} on stdout (surfaced verbatim); a missing command, a timeout, and
// empty output each get their own message.
func parseServerToken(out []byte, runErr error, timedOut bool) (serverToken, error) {
	var resp struct {
		Token      string `json:"token"`
		ControlURL string `json:"control_url"`
		Error      string `json:"error"`
	}
	_ = json.Unmarshal(out, &resp)
	switch {
	case resp.Token != "" && resp.ControlURL != "":
		return serverToken{token: resp.Token, controlURL: strings.TrimRight(resp.ControlURL, "/")}, nil
	case resp.Error != "":
		return serverToken{}, fmt.Errorf("mint server-identity token: %s", resp.Error)
	case timedOut:
		return serverToken{}, fmt.Errorf("`vesta-cloud token` timed out after %s", vestaCloudTokenTimeout)
	case runErr != nil:
		return serverToken{}, fmt.Errorf("run `vesta-cloud token` (is the vesta-cloud skill installed?): %w", runErr)
	default:
		return serverToken{}, fmt.Errorf("`vesta-cloud token` returned no token")
	}
}

// authorize resolves the base URL and Authorization header for the agent's chosen
// --source, plus which path family to use. `switchboard` uses the static sbk_ key
// against native /leases paths; `vesta-cloud` mints one short-lived server-identity
// token and hits vesta.run's /reserve, /code, /release. There is no fallback
// between sources: a source whose prerequisites are missing errors precisely.
// A caller making several requests (the code poll) resolves once and reuses it.
func (c *client) authorize() (base, auth string, direct bool, err error) {
	if c.source == sourceSwitchboard {
		if c.cfg.configError != "" {
			return "", "", false, errors.New(c.cfg.configError)
		}
		if !c.isDirect() {
			return "", "", false, errors.New("--source switchboard needs SWITCHBOARD_API_URL and SWITCHBOARD_API_KEY set together (an sbk_ key from whoever runs that Switchboard)")
		}
		return c.cfg.directURL, "Bearer " + c.cfg.directKey, true, nil
	}
	st, err := mintServerToken()
	if err != nil {
		return "", "", false, err
	}
	return st.controlURL + "/integrations/switchboard", "Bearer " + st.token, false, nil
}

type lease struct {
	ID      string `json:"id"`
	Number  string `json:"number"`
	Service string `json:"service"`
}

// reserve claims a temporary number for one service. Cloud mode POSTs the forwarded
// /reserve; direct mode POSTs native /leases. A spent quota comes back errQuotaExceeded
// and an empty pool errOutOfStock, both surfaced as a clean status. A non-empty
// idempotencyKey is passed through so a retried reserve for the same flow returns the
// same number instead of drawing (and paying for) a second one.
func (c *client) reserve(service, country, idempotencyKey string) (lease, error) {
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
	if idempotencyKey != "" {
		body["idempotency_key"] = idempotencyKey
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
