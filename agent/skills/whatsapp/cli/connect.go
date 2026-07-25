package main

import (
	"flag"
	"fmt"
	"os"
)

type connectOptions struct {
	opener             string
	phone              string
	instance           string
	ownNumber          bool
	port               int
	acknowledgeBanRisk bool
	openerSet          bool
	phoneSet           bool
	portSet            bool
	acknowledgeSet     bool
}

// parseConnectOptions owns every flag accepted by the setup wrapper. Parsing
// happens before mode selection or daemon startup, so help, typos, and invalid
// combinations cannot fall through into a live pairing attempt.
func parseConnectOptions(name string, args []string) (connectOptions, error) {
	var opts connectOptions
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.StringVar(&opts.opener, "opener", "", "Managed number greeting prefilled in the user's wa.me link")
	fs.StringVar(&opts.phone, "phone", "", "Self-hosted pairing-code fallback for this E.164 account number")
	fs.StringVar(&opts.instance, "instance", "", "Named WhatsApp instance")
	fs.BoolVar(&opts.ownNumber, "own-number", false, "Hosted pool number that the user registers and owns")
	fs.IntVar(&opts.port, "port", 0, "Self-hosted QR page port (0 = register a public service)")
	fs.BoolVar(&opts.acknowledgeBanRisk, "acknowledge-ban-risk", false, "Override the pairing rate limit")
	if err := parseFlags(fs, args); err != nil {
		return connectOptions{}, err
	}
	if fs.NArg() != 0 {
		return connectOptions{}, fmt.Errorf("connect takes flags only, got %q", fs.Arg(0))
	}
	fs.Visit(func(f *flag.Flag) {
		switch f.Name {
		case "opener":
			opts.openerSet = true
		case "phone":
			opts.phoneSet = true
		case "port":
			opts.portSet = true
		case "acknowledge-ban-risk":
			opts.acknowledgeSet = true
		}
	})
	if opts.phoneSet && opts.phone == "" {
		return connectOptions{}, fmt.Errorf("--phone requires the E.164 account number")
	}
	if opts.phone != "" && opts.ownNumber {
		return connectOptions{}, fmt.Errorf("--phone and --own-number select different account types")
	}
	if opts.phone != "" && opts.portSet {
		return connectOptions{}, fmt.Errorf("--phone uses a pairing code and cannot be combined with the QR-only --port")
	}
	return opts, nil
}

func validateConnectMode(opts connectOptions, hosted bool) error {
	if opts.ownNumber {
		if opts.openerSet {
			return fmt.Errorf("--opener applies only to a managed hosted number, not --own-number")
		}
		return nil
	}
	if hosted {
		if opts.phoneSet {
			return fmt.Errorf("--phone is for a self-hosted account; this box manages its number through `whatsapp connect`")
		}
		if opts.portSet {
			return fmt.Errorf("--port applies only to a self-hosted QR page")
		}
		if opts.acknowledgeSet {
			return fmt.Errorf("--acknowledge-ban-risk applies only to self-hosted pairing")
		}
		return nil
	}
	if opts.openerSet {
		return fmt.Errorf("--opener applies only to a managed hosted number")
	}
	return nil
}

// canonicalConnectArgs makes the parsed options authoritative for every legacy
// helper downstream. In particular, Go's valid -flag and --bool=true spellings
// must not be accepted here and then silently ignored by raw os.Args scanners.
func canonicalConnectArgs(program string, opts connectOptions) []string {
	args := []string{program}
	appendValue := func(name, value string) {
		if value != "" {
			args = append(args, "--"+name, value)
		}
	}
	appendValue("opener", opts.opener)
	appendValue("phone", opts.phone)
	appendValue("instance", opts.instance)
	if opts.ownNumber {
		args = append(args, "--own-number")
	}
	if opts.portSet {
		args = append(args, "--port", fmt.Sprintf("%d", opts.port))
	}
	if opts.acknowledgeBanRisk {
		args = append(args, "--acknowledge-ban-risk")
	}
	return args
}

// runConnect is the agent's single WhatsApp setup verb. It makes the same
// paradigm choice the daemon's chooseLinker does (a hosted box claims + links its
// own managed number; a plain box links the user's own WhatsApp by QR), so the
// agent runs `whatsapp connect` and never has to know which mode the box is in.
// Idempotent and safe to re-run until `whatsapp status` shows linked. The hidden
// `provision` and `link` aliases route here too.
func runConnect() {
	opts, err := parseConnectOptions("connect", os.Args[1:])
	if err != nil {
		failJSON("%s", err.Error())
	}
	os.Args = canonicalConnectArgs(os.Args[0], opts)
	cfg := managedConfigFromEnvAndState()
	hosted := newManagedAuth(cfg).isHosted()
	if err := validateConnectMode(opts, hosted); err != nil {
		failJSON("%s", err.Error())
	}
	if opts.ownNumber {
		runConnectOwnNumber()
		return
	}
	if hosted {
		runProvision(opts.opener)
		return
	}
	if opts.phone != "" {
		runLinkPhone(opts.phone)
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
	lock, err := acquireConnectLock()
	if err != nil {
		failJSON("%s", err.Error())
	}
	defer releaseConnectLock(lock)
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
