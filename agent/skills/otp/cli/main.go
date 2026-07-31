package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
)

// otp: get a one-time SMS verification code on a temporary phone number, to sign up
// for or verify any service. Three verbs: new (reserve a number), code (wait for the
// SMS), release (give the number back). See ../SKILL.md.

func main() {
	if len(os.Args) < 2 {
		printUsage(os.Stdout)
		os.Exit(0)
	}
	cmd := os.Args[1]
	args := os.Args[2:]
	switch cmd {
	case "new":
		runNew(args)
	case "code":
		runCode(args)
	case "release":
		runRelease(args)
	case "-h", "--help", "help":
		printUsage(os.Stdout)
	default:
		failJSON("unknown command %q (use: new | code | release)", cmd)
	}
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: otp <command> [flags]")
	fmt.Fprintln(w, "  new --service <name> [--country US]   reserve a temporary number for a service; prints {number, id}")
	fmt.Fprintln(w, "  code --id <id> [--since <RFC3339>]    wait for the SMS code on that number; prints {code}")
	fmt.Fprintln(w, "  release --id <id>                     give the number back when done; prints {}")
}

func runNew(args []string) {
	fs := flag.NewFlagSet("new", flag.ContinueOnError)
	service := fs.String("service", "", "the service the code is for (required)")
	country := fs.String("country", "", "optional ISO country code, e.g. US")
	if err := fs.Parse(args); err != nil {
		failJSON("%v", err)
	}
	if *service == "" {
		failJSON("--service is required")
	}
	l, err := newClient(loadConfig()).reserve(*service, *country)
	if err != nil {
		failReserve(err)
	}
	printJSON(map[string]string{"number": l.Number, "id": l.ID})
}

func runCode(args []string) {
	fs := flag.NewFlagSet("code", flag.ContinueOnError)
	id := fs.String("id", "", "the reservation id from `otp new` (required)")
	since := fs.String("since", "", "optional RFC3339 timestamp: only codes texted after it")
	if err := fs.Parse(args); err != nil {
		failJSON("%v", err)
	}
	if *id == "" {
		failJSON("--id is required")
	}
	code, err := newClient(loadConfig()).pollCode(*id, *since)
	if errors.Is(err, errStillPending) {
		// Not a failure: the SMS has not arrived yet. Re-run to keep waiting.
		printJSON(map[string]string{
			"status": "pending",
			"next":   fmt.Sprintf("no code yet; re-run: otp code --id %s", *id),
		})
		return
	}
	if err != nil {
		failJSON("%v", err)
	}
	printJSON(map[string]string{"code": code})
}

func runRelease(args []string) {
	fs := flag.NewFlagSet("release", flag.ContinueOnError)
	id := fs.String("id", "", "the reservation id to release (required)")
	if err := fs.Parse(args); err != nil {
		failJSON("%v", err)
	}
	if *id == "" {
		failJSON("--id is required")
	}
	if err := newClient(loadConfig()).release(*id); err != nil {
		failJSON("%v", err)
	}
	printJSON(map[string]string{})
}

// failReserve turns reserve's terminal outcomes into a clean {error, next} status.
func failReserve(err error) {
	switch {
	case errors.Is(err, errQuotaExceeded):
		printJSON(map[string]string{
			"error": "otp_quota_exceeded",
			"next":  "the account's OTP allowance is spent; wait for it to reset, do not retry in a loop",
		})
	case errors.Is(err, errOutOfStock):
		printJSON(map[string]string{
			"error": "out_of_stock",
			"next":  "no number is free right now; retry shortly, or pass a different --country",
		})
	default:
		printJSON(map[string]string{"error": err.Error()})
	}
	os.Exit(1)
}

func printJSON(v any) {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(data))
}

// failJSON prints an {"error": ...} object and exits nonzero.
func failJSON(format string, args ...any) {
	printJSON(map[string]any{"error": fmt.Sprintf(format, args...)})
	os.Exit(1)
}
