package main

import (
	"context"
	"errors"
	"fmt"
	"time"
)

// errPairingInProgress is returned when a pairing op is asked for while another
// already holds the single-flight (beginPairing). One pairing at a time.
var errPairingInProgress = errors.New("a pairing (provision/link) is already in progress; retry in a moment")

// errRateLimited is returned when the ban-avoidance rate-limit guard blocks a
// managed pairing before any PairPhone code is minted. It wraps the guard's own
// message (which carries the cooldown window) so the agent gets a clean status.
var errRateLimited = errors.New("the pairing rate limit was reached")

// linkResult is the terminal outcome of a successful pairing.
type linkResult struct {
	MSISDN string // the linked number; empty for a QR-linked user account
}

// linker is the box's pairing strategy, chosen once at construction (chooseLinker)
// and never branched on inline again. Two paradigms: qrLinker links the USER's own
// WhatsApp (QR scan or phone code); managedLinker links the agent's OWN pooled
// number (whose 3-source credential is hidden inside managedAuth). Each impl serves
// the operations its paradigm supports and rejects the others with a clear message,
// so the mode decision lives in the constructed value, not in scattered isHosted checks.
type linker interface {
	name() string
	// provision links this box's own managed number (blocking, self-contained).
	provision(wac *WhatsAppClient) (linkResult, error)
	// linkQR serves the QR page on port (0 = none) and blocks until scan or timeout,
	// leaving the client clean on failure.
	linkQR(wac *WhatsAppClient, port int) (linkResult, error)
	// pairCode generates one pairing code for the user's phone to enter.
	pairCode(wac *WhatsAppClient, phone string) (string, error)
}

// chooseLinker makes the one construction-time paradigm decision. It first
// reconciles direct-mode pool creds with persisted state so they survive an env
// scrub (env creds win and are persisted; otherwise the persisted ones fill the
// config), then returns the managed linker when the box can reach a pool, else QR.
func chooseLinker(cfg managedConfig, state *stateStore) linker {
	if cfg.directURL != "" && cfg.directKey != "" {
		state.update(func(s *daemonState) { s.DirectURL, s.DirectKey = cfg.directURL, cfg.directKey })
	} else {
		snap := state.snapshot()
		if cfg.directURL == "" {
			cfg.directURL = snap.DirectURL
		}
		if cfg.directKey == "" {
			cfg.directKey = snap.DirectKey
		}
	}
	auth := newManagedAuth(cfg)
	if auth.isHosted() {
		return &managedLinker{auth: auth, state: state}
	}
	return qrLinker{}
}

// qrLinker links the user's own WhatsApp account (self-hosted paradigm).
type qrLinker struct{}

func (qrLinker) name() string { return "self-hosted" }

func (qrLinker) provision(*WhatsAppClient) (linkResult, error) {
	return linkResult{}, fmt.Errorf("managed WhatsApp is only available on a hosted (vesta.run) box; this box links the user's own WhatsApp: run `whatsapp connect`")
}

func (qrLinker) linkQR(wac *WhatsAppClient, port int) (linkResult, error) {
	return wac.runQRLink(port)
}

func (qrLinker) pairCode(wac *WhatsAppClient, phone string) (string, error) {
	return wac.generatePairCode(phone)
}

// managedLinker links the agent's own pooled number (managed paradigm). It holds
// the managedAuth HTTP client (which hides the 3-credential selection) and the
// state store (which owns the persisted number).
type managedLinker struct {
	auth  *managedAuth
	state *stateStore
}

func (*managedLinker) name() string { return "managed" }

func (*managedLinker) linkQR(*WhatsAppClient, int) (linkResult, error) {
	return linkResult{}, fmt.Errorf("this managed (vesta.run) box links its own pooled number; run `whatsapp connect`")
}

func (*managedLinker) pairCode(*WhatsAppClient, string) (string, error) {
	return "", fmt.Errorf("this managed (vesta.run) box links its own pooled number; run `whatsapp connect`, not a phone pairing code")
}

// provision claims (or re-links) this box's managed number and links the companion,
// synchronously. It leaves the client CLEAN (disconnected) on every failure path so
// the next attempt starts fresh (never a GetQRChannel-on-connected-client error).
func (l *managedLinker) provision(wac *WhatsAppClient) (linkResult, error) {
	// Bring the pairing WS up. We link by phone code, so the QR channel is drained
	// unused: GetQRChannel must precede Connect, and PairPhone waits for the WS.
	qrChan, err := wac.client.GetQRChannel(context.Background())
	if err != nil {
		return linkResult{}, fmt.Errorf("open pairing channel: %w", err)
	}
	if err := wac.client.Connect(); err != nil {
		wac.client.Disconnect()
		return linkResult{}, fmt.Errorf("connect: %w", err)
	}
	// Drain the unused QR codes for the life of this call so whatsmeow's emitter
	// never blocks during the long, server-synchronous /pair. Scoped to this one
	// synchronous call: a manual Disconnect does NOT close qrChan (whatsmeow only
	// closes it on PairSuccess or an unexpected drop), so the drain exits on the
	// deferred done signal instead, otherwise it would leak on every failure path.
	drainDone := make(chan struct{})
	defer close(drainDone)
	go func() {
		for {
			select {
			case _, ok := <-qrChan:
				if !ok {
					return
				}
			case <-drainDone:
				return
			}
		}
	}()

	// Always re-consult the idempotent POST /provision (inside auth.provision),
	// even when a number is already saved: the control plane auto-heals a banned
	// account onto a FRESH number, so a post-link ban is picked up here instead of
	// blindly re-pairing the stale (dead) saved number forever. The pairing code is
	// minted through the ban-avoidance guard, at the same safe rate as the phone path.
	st, err := l.auth.provision(l.guardedPairPhone(wac.PairPhone))
	if err != nil {
		wac.client.Disconnect()
		return linkResult{}, err
	}
	l.state.update(func(s *daemonState) { s.MSISDN = st.MSISDN })

	deadline := time.Now().Add(ManagedLinkTimeout)
	for time.Now().Before(deadline) {
		if wac.client.IsLoggedIn() {
			wac.onLinked()
			wac.logger.Infof("Managed WhatsApp linked (%s)", st.MSISDN)
			return linkResult{MSISDN: st.MSISDN}, nil
		}
		time.Sleep(ConnectRetryDelay)
	}
	wac.client.Disconnect()
	return linkResult{}, fmt.Errorf("pairing code accepted but the companion did not finish linking within %s; retry `whatsapp connect`", ManagedLinkTimeout)
}

// guardedPairPhone wraps PairPhone in the same ban-avoidance rate-limit guard the
// phone-code path uses, so re-running `whatsapp connect` on a number that keeps
// failing to finish linking cannot issue unbounded real PairPhone requests (the
// exact auto-ban pattern). It checks the cap BEFORE minting a code and records the
// attempt only once a code is actually generated (a pre-code failure burns no
// slot); when the cap is reached it returns errRateLimited and never calls
// PairPhone. The managed path has no --acknowledge-ban-risk flag, so the guard is
// never overridden here.
func (l *managedLinker) guardedPairPhone(pair func(msisdn string) (string, error)) func(msisdn string) (string, error) {
	return func(msisdn string) (string, error) {
		now := time.Now()
		if err := checkPairAttempt(l.state.snapshot().PairAttempts, now, false); err != nil {
			return "", fmt.Errorf("%w: %w", errRateLimited, err)
		}
		code, err := pair(msisdn)
		if err != nil {
			return "", err
		}
		l.state.recordPairAttempt(now)
		return code, nil
	}
}
