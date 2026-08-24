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
	fmt.Fprintln(w, "Usage: otp <command> --source <vesta-cloud|switchboard> [flags]")
	fmt.Fprintln(w, "  new --source <s> --service <name> [--country US] [--idempotency-key <k>]   reserve a temporary number for a service; prints {number, id}")
	fmt.Fprintln(w, "  code --source <s> --id <id> [--since <RFC3339>]    wait for the SMS code on that number; prints {code}")
	fmt.Fprintln(w, "  release --source <s> --id <id>                     give the number back when done; prints {}")
	fmt.Fprintln(w, "  --source states where the number comes from; you decide, the CLI never guesses:")
	fmt.Fprintln(w, "    vesta-cloud  Vesta Cloud (needs this box's Vesta Cloud account)")
	fmt.Fprintln(w, "    switchboard  a Switchboard the owner runs (needs SWITCHBOARD_API_URL + SWITCHBOARD_API_KEY)")
}

// parseSource validates the required --source value. The agent states the
// source explicitly; there is no detection and no fallback.
func parseSource(raw string) string {
	switch raw {
	case sourceVestaCloud, sourceSwitchboard:
		return raw
	case "":
		failJSON("--source is required: vesta-cloud (Vesta Cloud) or switchboard (a Switchboard the owner runs)")
	default:
		failJSON("unknown --source %q (use: vesta-cloud | switchboard)", raw)
	}
	return "" // unreachable
}

func runNew(args []string) {
	fs := flag.NewFlagSet("new", flag.ContinueOnError)
	source := fs.String("source", "", "where the number comes from: vesta-cloud | switchboard (required)")
	service := fs.String("service", "", "the service the code is for (required)")
	country := fs.String("country", "", "optional ISO country code, e.g. US")
	idempotencyKey := fs.String("idempotency-key", "", "optional stable key: reuse it when retrying a reserve for the same flow so it returns the same number instead of drawing another")
	if err := fs.Parse(args); err != nil {
		failJSON("%v", err)
	}
	if *service == "" {
		failJSON("--service is required")
	}
	l, err := newClient(loadConfig(), parseSource(*source)).reserve(*service, *country, *idempotencyKey)
	if err != nil {
		failReserve(err)
	}
	printJSON(map[string]string{"number": l.Number, "id": l.ID})
}

func runCode(args []string) {
	fs := flag.NewFlagSet("code", flag.ContinueOnError)
	source := fs.String("source", "", "the same --source the number was reserved with (required)")
	id := fs.String("id", "", "the reservation id from `otp new` (required)")
	since := fs.String("since", "", "optional RFC3339 timestamp: only codes texted after it")
	if err := fs.Parse(args); err != nil {
		failJSON("%v", err)
	}
	if *id == "" {
		failJSON("--id is required")
	}
	src := parseSource(*source)
	code, err := newClient(loadConfig(), src).pollCode(*id, *since)
	if errors.Is(err, errStillPending) {
		// Not a failure: the SMS has not arrived yet. Re-run to keep waiting.
		printJSON(map[string]string{
			"status": "pending",
			"next":   fmt.Sprintf("no code yet; re-run: otp code --source %s --id %s", src, *id),
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
	source := fs.String("source", "", "the same --source the number was reserved with (required)")
	id := fs.String("id", "", "the reservation id to release (required)")
	if err := fs.Parse(args); err != nil {
		failJSON("%v", err)
	}
	if *id == "" {
		failJSON("--id is required")
	}
	if err := newClient(loadConfig(), parseSource(*source)).release(*id); err != nil {
		failJSON("%v", err)
	}
	printJSON(map[string]string{})
}

// failReserve turns reserve's terminal outcomes into a clean {error, next} envelope.
func failReserve(err error) {
	switch {
	case errors.Is(err, errQuotaExceeded):
		failObject(map[string]string{
			"error": "otp_quota_exceeded",
			"next":  "the account's OTP allowance is spent; wait for it to reset, do not retry in a loop",
		})
	case errors.Is(err, errOutOfStock):
		failObject(map[string]string{
			"error": "out_of_stock",
			"next":  "no number is free right now; retry shortly, or pass a different --country",
		})
	default:
		failObject(map[string]string{"error": err.Error()})
	}
}

// printJSON prints a success result; failures go through failJSON or failObject.
// The envelope is single-line JSON: agents truncate output (`tail -1`), and a
// pretty-printed envelope's last line is "}" whether it succeeded or failed.
func printJSON(v any) {
	data, err := json.Marshal(v)
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(data))
}

// failObject is the one owner of the failure stream: the envelope prints on
// stderr with a non-zero exit, so stdout carries only success output and a
// filter piped onto stdout can never swallow a failure or its explanation.
func failObject(v any) {
	data, _ := json.Marshal(v)
	fmt.Fprintln(os.Stderr, string(data))
	os.Exit(1)
}

// failJSON prints an {"error": ...} object on stderr and exits nonzero.
func failJSON(format string, args ...any) {
	failObject(map[string]any{"error": fmt.Sprintf(format, args...)})
}
