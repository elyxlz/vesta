package main

// runConnect is the agent's single WhatsApp setup verb. It makes the same
// paradigm choice the daemon's chooseLinker does (a hosted box claims + links its
// own managed number; a plain box links the user's own WhatsApp by QR), so the
// agent runs `whatsapp connect` and never has to know which mode the box is in.
// Idempotent and safe to re-run until `whatsapp status` shows linked. The hidden
// `provision` and `link` aliases route here too.
func runConnect() {
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
