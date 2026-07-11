package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestUsageListsLifecycleCommands(t *testing.T) {
	var buf bytes.Buffer
	printUsage(&buf)
	out := buf.String()
	for _, want := range []string{"daemon", "link", "serve", "send-message"} {
		if !strings.Contains(out, want) {
			t.Errorf("usage output missing %q", want)
		}
	}
}

func TestIsHelpArg(t *testing.T) {
	cases := map[string]bool{"--help": true, "-h": true, "help": true, "send": false, "serve": false}
	for arg, want := range cases {
		if got := isHelpArg(arg); got != want {
			t.Errorf("isHelpArg(%q) = %v, want %v", arg, got, want)
		}
	}
}
