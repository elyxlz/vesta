package main

import (
	"fmt"
	"os"
)

// runConnect is the agent's single WhatsApp setup verb. It makes the same
// paradigm choice the daemon's chooseLinker does (a hosted box claims + links its
// own managed number; a plain box links the user's own WhatsApp by QR), so the
// agent runs `whatsapp connect` and never has to know which mode the box is in.
// Idempotent and safe to re-run until `whatsapp status` shows linked. The hidden
// `provision` and `link` aliases route here too.
func runConnect() {
	if hasBareFlag("own-number") {
		runConnectOwnNumber()
		return
	}
	cfg := loadManagedConfig()
	// Fill direct-mode pool creds from persisted state when the env lacks them,
	// mirroring chooseLinker, so an env scrub still selects the managed path.
	if cfg.directURL == "" || cfg.directKey == "" {
		st := loadStateFromDisk(stateDataDir())
		if cfg.directURL == "" {
			cfg.directURL = st.DirectURL
		}
		if cfg.directKey == "" {
			cfg.directKey = st.DirectKey
		}
	}
	if newManagedAuth(cfg).isHosted() {
		runProvision()
		return
	}
	runLink()
}

// managedConfigFromEnvAndState builds the managed config, filling direct-mode pool
// creds from persisted state when the env lacks them (mirrors chooseLinker), so an
// env scrub still resolves the managed path.
func managedConfigFromEnvAndState() managedConfig {
	cfg := loadManagedConfig()
	if cfg.directURL == "" || cfg.directKey == "" {
		st := loadStateFromDisk(stateDataDir())
		if cfg.directURL == "" {
			cfg.directURL = st.DirectURL
		}
		if cfg.directKey == "" {
			cfg.directKey = st.DirectKey
		}
	}
	return cfg
}

// runConnectOwnNumber is the user-owned ("bring your own device") setup: the pool
// API reserves a number and relays its SMS code, the USER registers it on their own
// phone, and the agent then links only as a companion. The user owns the primary and
// keeps their phone online (they reauth), unlike the managed reply-first onboarding
// where the agent drives a headless primary. Reached via `whatsapp connect --own-number`.
func runConnectOwnNumber() {
	auth := newManagedAuth(managedConfigFromEnvAndState())
	if !auth.isHosted() {
		failJSON("`whatsapp connect --own-number` needs a hosted (vesta.run) box to draw a pool number; a plain box links the user's own WhatsApp with `whatsapp connect`")
	}
	number, err := auth.provisionSelf()
	if err != nil {
		failJSON("could not reserve a user-owned number: %v", err)
	}
	printJSON(map[string]any{
		"status": "register_number",
		"number": number,
		"next":   fmt.Sprintf("Relay to the user: on their OWN phone, open WhatsApp and register THIS number: %s. Start the SMS verification; I fetch the code next. The user owns this number and must keep their phone online.", number),
	})
	code, err := auth.selfNumberOTP()
	if err != nil {
		failJSON("could not fetch the verification code: %v", err)
	}
	printJSON(map[string]any{
		"status": "enter_code",
		"number": number,
		"code":   code,
		"next":   "Relay to the user: enter this code in WhatsApp to finish registering the number on their phone. Once WhatsApp confirms, scan the link page below to add me as a companion device.",
	})
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}
	output, exitCode := serveAndRunQRLink("own-number-link")
	if exitCode != 0 {
		fmt.Println(string(output))
		os.Exit(1)
	}
	printJSON(map[string]any{
		"status": "linked",
		"owner":  "user",
		"number": number,
		"note":   fmt.Sprintf("Linked as a companion to %s, which the USER owns on their own phone. They must keep that phone online; if it drops, the user re-links. This is not the managed reply-first flow: the number is the user's, so there is no wa.me onboarding and normal messaging applies.", number),
	})
}
