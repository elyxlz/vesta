package main

import (
	"strings"
	"testing"
)

// The incident this guards against: an agent sent
//
//	whatsapp send --to <chat> --message "first bubble" --message "second bubble"
//
// Go's flag package silently keeps only the LAST value of a repeated single-value
// flag, so "first bubble" was dropped and only "second bubble" was delivered; the
// user saw a message go missing with no error anywhere. parseFlags now rejects the
// repeat before any send happens.

// runSend drives the real send handler. A duplicate flag must be rejected at parse
// time (nil client: nothing past parsing is ever reached); when no flag repeats,
// parsing proceeds and the handler reaches its own --to validation, which is how
// the "parsing proceeds" cases below prove the pre-scan stayed quiet.
func runSend(t *testing.T, args []string) error {
	t.Helper()
	_, err := cmdSendMessage(args, nil)
	return err
}

func TestRepeatedValueFlagIsRejected(t *testing.T) {
	cases := []struct {
		name string
		args []string
		flag string
	}{
		{
			name: "the incident: two --message values",
			args: []string{"--to", "a chat", "--message", "first bubble", "--message", "second bubble"},
			flag: "--message",
		},
		{
			name: "inline = values",
			args: []string{"--to", "a chat", "--message=hello", "--message=world"},
			flag: "--message",
		},
		{
			name: "single-dash flag form",
			args: []string{"--to", "a chat", "-message", "one", "-message", "two"},
			flag: "--message",
		},
		{
			name: "inline and separate forms mix",
			args: []string{"--message=one", "--message", "two"},
			flag: "--message",
		},
		{
			name: "the recipient flag equally",
			args: []string{"--to", "a chat", "--message", "hi", "--to", "another chat"},
			flag: "--to",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := runSend(t, tc.args)
			if err == nil {
				t.Fatalf("send accepted %q; want a duplicate-flag rejection", tc.args)
			}
			if !strings.Contains(err.Error(), "given more than once") {
				t.Fatalf("error %q does not look like a duplicate-flag rejection", err)
			}
			if !strings.Contains(err.Error(), tc.flag) {
				t.Fatalf("error %q does not name the repeated flag %s", err, tc.flag)
			}
		})
	}
}

// The guard lives in parseFlags, not in send: every subcommand's value flags are covered.
func TestRepeatedValueFlagRejectedOnOtherSubcommands(t *testing.T) {
	_, err := cmdSendFile([]string{"--to", "a chat", "--file-path", "/tmp/one", "--file-path", "/tmp/two"}, nil)
	if err == nil || !strings.Contains(err.Error(), "given more than once") || !strings.Contains(err.Error(), "--file-path") {
		t.Fatalf("send-file with a repeated --file-path got %v, want a duplicate-flag rejection naming --file-path", err)
	}
	_, err = cmdListMessages([]string{"--to", "a chat", "--to", "another chat"}, nil)
	if err == nil || !strings.Contains(err.Error(), "given more than once") || !strings.Contains(err.Error(), "--to") {
		t.Fatalf("list-messages with a repeated --to got %v, want a duplicate-flag rejection naming --to", err)
	}
}

// Cases that must NOT trip the duplicate check: parsing proceeds and the handler
// reaches its own "--to is required" validation, proving the args were parsed.
func TestNoDuplicateErrorWhenNoValueFlagRepeats(t *testing.T) {
	cases := []struct {
		name string
		args []string
	}{
		{
			name: "each flag given once",
			args: []string{"--message", "only bubble"},
		},
		{
			// Accepted limitation: a repeated bool flag carries no value to drop.
			name: "repeated bool flag is allowed",
			args: []string{"--message", "hi", "--longform", "--longform"},
		},
		{
			name: "a value token identical to the flag name is a value, not a repeat",
			args: []string{"--message", "--message"},
		},
		{
			name: "a value that names another declared flag is still just a value",
			args: []string{"--message", "--to"},
		},
		{
			name: "tokens after -- are positionals, not flag occurrences",
			args: []string{"--message", "a", "--", "--message", "b"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := runSend(t, tc.args)
			if err == nil || !strings.Contains(err.Error(), "--to is required") {
				t.Fatalf("send of %q got %v; want parsing to proceed to --to validation", tc.args, err)
			}
		})
	}
}

// Unknown tokens are nobody's duplicate: the FlagSet's own "not defined" rejection
// keeps owning that case, so a repeated unknown flag reports what it actually is.
func TestRepeatedUnknownTokenIsNotADuplicateError(t *testing.T) {
	_, err := cmdHangup([]string{"--nope", "--nope"}, nil)
	if err == nil || !strings.Contains(err.Error(), "not defined") {
		t.Fatalf("hangup with a repeated unknown flag got %v, want the FlagSet's own rejection", err)
	}
	if strings.Contains(err.Error(), "more than once") {
		t.Fatalf("error %q reports a duplicate for a flag the command does not declare", err)
	}
}
