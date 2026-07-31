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
	if opts.phone != "" && opts.portSet {
		return connectOptions{}, fmt.Errorf("--phone uses a pairing code and cannot be combined with the QR-only --port")
	}
	return opts, nil
}

func validateConnectMode(opts connectOptions, hosted bool) error {
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
