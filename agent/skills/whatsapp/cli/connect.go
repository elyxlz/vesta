package main

import (
	"flag"
	"fmt"
	"os"
)

// The three account sources the agent chooses between with `--source`.
// vesta-cloud and doubletick both link a headless (pooled) account;
// self-managed links the user's own.
const (
	sourceVestaCloud  = "vesta-cloud"
	sourceDoubletick  = "doubletick"
	sourceSelfManaged = "self-managed"
)

type connectOptions struct {
	source             string
	opener             string
	phone              string
	instance           string
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
	fs.StringVar(&opts.source, "source", "", "Account source: vesta-cloud, doubletick, or self-managed (required)")
	fs.StringVar(&opts.opener, "opener", "", "Opener for a headless account, prefilled in the user's wa.me link")
	fs.StringVar(&opts.phone, "phone", "", "Self-managed pairing-code fallback for this E.164 account number")
	fs.StringVar(&opts.instance, "instance", "", "Named WhatsApp instance")
	fs.IntVar(&opts.port, "port", 0, "Self-managed QR page port (0 = register a public service)")
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
	if opts.phone != "" && opts.portSet {
		return connectOptions{}, fmt.Errorf("--phone uses a pairing code and cannot be combined with the QR-only --port")
	}
	return opts, nil
}

// validateConnectSource enforces the required --source and the flag/mode pairings.
// --opener belongs to the headless sources (vesta-cloud, doubletick); --phone/--port/
// --acknowledge-ban-risk belong to self-managed pairing. An absent or unknown source
// errors before any environment probing or daemon startup.
func validateConnectSource(opts connectOptions) error {
	switch opts.source {
	case "":
		return fmt.Errorf("connect requires --source: vesta-cloud (a vesta.run managed VM), doubletick (DOUBLETICK_API_URL/KEY set), or self-managed (the user's own account)")
	case sourceVestaCloud, sourceDoubletick:
		if opts.phoneSet {
			return fmt.Errorf("--phone is for a self-managed account; a headless account is set up with `whatsapp connect --source vesta-cloud` or `--source doubletick`")
		}
		if opts.portSet {
			return fmt.Errorf("--port applies only to a self-managed QR page")
		}
		if opts.acknowledgeSet {
			return fmt.Errorf("--acknowledge-ban-risk applies only to self-managed pairing")
		}
	case sourceSelfManaged:
		if opts.openerSet {
			return fmt.Errorf("--opener applies only to a headless account (--source vesta-cloud or doubletick)")
		}
	default:
		return fmt.Errorf("invalid --source %q: use vesta-cloud, doubletick, or self-managed", opts.source)
	}
	return nil
}

// connectRoute is the validated internal path a `connect --source` resolves to: one
// of runProvision (headless) / runLinkPhone / runLink. source is the resolved account
// source, threaded to the daemon's provision command so the agent's explicit choice
// (not the daemon's boot-time env) pins the pairing auth path: `vesta-cloud` makes a warm
// daemon mint a server-identity token even when it also booted with direct creds.
type connectRoute struct {
	provision bool
	opener    string
	linkPhone string
	source    string
	directURL string
	directKey string
}

// resolveConnect validates --source against the box environment and returns the path
// to run. vesta-cloud runs the managed pool a Vesta-provisioned VM ships with; doubletick
// demands the direct pool creds. self-managed always links the user's own account,
// by phone code when --phone is given, else by QR.
func resolveConnect(opts connectOptions, cfg managedConfig) (connectRoute, error) {
	if err := validateConnectSource(opts); err != nil {
		return connectRoute{}, err
	}
	switch opts.source {
	case sourceVestaCloud:
		if !cfg.isManagedVM() {
			return connectRoute{}, fmt.Errorf("--source vesta-cloud runs the managed WhatsApp of a vesta.run managed VM (`vesta-cloud whoami` reports managed_infra true there). This box is not one; a Vesta Cloud account alone opens managed WhatsApp only with an active paid membership. Use --source self-managed for the user's own WhatsApp")
		}
		return connectRoute{provision: true, opener: opts.opener, source: sourceVestaCloud}, nil
	case sourceDoubletick:
		if !cfg.isDirect() {
			return connectRoute{}, fmt.Errorf("--source doubletick needs DOUBLETICK_API_URL and DOUBLETICK_API_KEY set together")
		}
		return connectRoute{
			provision: true,
			opener:    opts.opener,
			source:    sourceDoubletick,
			directURL: cfg.directURL,
			directKey: cfg.directKey,
		}, nil
	default: // sourceSelfManaged, already validated above
		// A box on the managed-pool paradigm cannot link the user's own account:
		// its daemon builds a managed linker that rejects a QR/phone link.
		// Fail here with the fix, instead of dispatching to a link the daemon refuses.
		if cfg.isManagedVM() {
			return connectRoute{}, fmt.Errorf("--source self-managed cannot run on a vesta.run managed VM: its daemon links the managed pooled number; use --source vesta-cloud")
		}
		if cfg.isDirect() {
			return connectRoute{}, fmt.Errorf("--source self-managed conflicts with the DOUBLETICK_API_URL/KEY set on this box; use --source doubletick, or unset them to link the user's own account")
		}
		if opts.phone != "" {
			return connectRoute{linkPhone: opts.phone, source: sourceSelfManaged}, nil
		}
		return connectRoute{source: sourceSelfManaged}, nil
	}
}

// connect dispatch seams, overridable in tests so routing is verified without a
// daemon, socket, or network.
var (
	connectProvision = runProvision
	connectLink      = runLink
	connectLinkPhone = runLinkPhone
)

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
	if opts.portSet {
		args = append(args, "--port", fmt.Sprintf("%d", opts.port))
	}
	if opts.acknowledgeBanRisk {
		args = append(args, "--acknowledge-ban-risk")
	}
	return args
}

// runConnect is the agent's single WhatsApp setup verb. The agent states the account
// source with --source (vesta-cloud, doubletick, or self-managed); the CLI validates that
// the box environment can satisfy it and routes to the matching path, erring clearly
// when it cannot. There is no auto-detection: the mode is the agent's explicit choice.
// Idempotent and safe to re-run until `whatsapp status` shows linked.
func runConnect() {
	opts, err := parseConnectOptions("connect", os.Args[1:])
	if err != nil {
		failJSON("%s", err.Error())
	}
	route, err := resolveConnect(opts, managedConfigFromEnvAndState())
	if err != nil {
		failJSON("%s", err.Error())
	}
	os.Args = canonicalConnectArgs(os.Args[0], opts)
	dispatchConnectRoute(route)
}

func dispatchConnectRoute(route connectRoute) {
	switch {
	case route.provision:
		connectProvision(route.source, route.opener, route.directURL, route.directKey)
	case route.linkPhone != "":
		connectLinkPhone(route.linkPhone)
	default:
		connectLink()
	}
}

// runConnectAlias serves the hidden dev-only `provision` and `link` verbs. They are
// already explicit about the path, so they skip the --source requirement and route
// straight to runProvision (provision) or runLink/runLinkPhone (link), still parsing
// and canonicalizing their flags so downstream helpers see authoritative args.
func runConnectAlias(name string, provision bool) {
	opts, err := parseConnectOptions(name, os.Args[1:])
	if err != nil {
		failJSON("%s", err.Error())
	}
	os.Args = canonicalConnectArgs(os.Args[0], opts)
	dispatchConnectRoute(connectRoute{provision: provision, opener: opts.opener, linkPhone: opts.phone})
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
