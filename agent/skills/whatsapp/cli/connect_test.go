package main

import (
	"strings"
	"testing"
)

func TestParseConnectOptions(t *testing.T) {
	opts, err := parseConnectOptions("connect", []string{
		"--phone", "+393481234567",
		"--instance", "personal",
		"--acknowledge-ban-risk",
	})
	if err != nil {
		t.Fatalf("parseConnectOptions: %v", err)
	}
	if opts.phone != "+393481234567" {
		t.Errorf("phone = %q", opts.phone)
	}
	if opts.instance != "personal" {
		t.Errorf("instance = %q", opts.instance)
	}
	if !opts.acknowledgeBanRisk {
		t.Error("acknowledgeBanRisk = false")
	}
}

func TestConnectRejectsUnknownFlagsInsteadOfStartingQR(t *testing.T) {
	_, err := parseConnectOptions("connect", []string{"--phnoe", "+393481234567"})
	if err == nil {
		t.Fatal("unknown flag was accepted")
	}
	if !strings.Contains(err.Error(), "flag provided but not defined") {
		t.Fatalf("unknown flag error = %q", err)
	}
}

func TestConnectRejectsConflictingPairingMethods(t *testing.T) {
	for _, args := range [][]string{
		{"--phone", "+393481234567", "--own-number"},
		{"--phone", "+393481234567", "--port", "61012"},
	} {
		if _, err := parseConnectOptions("connect", args); err == nil {
			t.Errorf("parseConnectOptions(%q) accepted conflicting methods", args)
		}
	}
}

func TestConnectRejectsPositionalsAndEmptyPhone(t *testing.T) {
	for _, args := range [][]string{
		{"pair-now"},
		{"--phone="},
		{"-phone="},
	} {
		if _, err := parseConnectOptions("connect", args); err == nil {
			t.Errorf("parseConnectOptions(%q) accepted invalid input", args)
		}
	}
}

func TestCanonicalConnectArgsPreserveEveryAcceptedFlagSpelling(t *testing.T) {
	opts, err := parseConnectOptions("connect", []string{
		"-instance", "personal",
		"-port=61012",
		"--acknowledge-ban-risk=true",
	})
	if err != nil {
		t.Fatal(err)
	}
	got := strings.Join(canonicalConnectArgs("whatsapp", opts), " ")
	for _, want := range []string{
		"--instance personal",
		"--port 61012",
		"--acknowledge-ban-risk",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("canonical args = %q, missing %q", got, want)
		}
	}
}

func TestConnectRejectsFlagsThatDoNotApplyToTheSelectedMode(t *testing.T) {
	cases := []struct {
		args   []string
		hosted bool
	}{
		{[]string{"--port", "61012"}, true},
		{[]string{"--acknowledge-ban-risk"}, true},
		{[]string{"--opener", "hello"}, false},
		{[]string{"--own-number", "--opener", "hello"}, true},
	}
	for _, tc := range cases {
		opts, err := parseConnectOptions("connect", tc.args)
		if err != nil {
			t.Fatalf("parseConnectOptions(%q): %v", tc.args, err)
		}
		if err := validateConnectMode(opts, tc.hosted); err == nil {
			t.Errorf("validateConnectMode(%q, hosted=%v) accepted an ignored flag", tc.args, tc.hosted)
		}
	}
}

func TestConnectPreservesExplicitZeroPort(t *testing.T) {
	opts, err := parseConnectOptions("connect", []string{"--port", "0"})
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(canonicalConnectArgs("whatsapp", opts), " "); !strings.Contains(got, "--port 0") {
		t.Fatalf("canonical args = %q, want explicit --port 0", got)
	}
}
