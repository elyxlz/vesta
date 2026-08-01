package main

import (
	"os"
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

func TestConnectRequiresSource(t *testing.T) {
	opts, err := parseConnectOptions("connect", []string{"--opener", "hello"})
	if err != nil {
		t.Fatalf("parseConnectOptions: %v", err)
	}
	err = validateConnectSource(opts)
	if err == nil {
		t.Fatal("a bare connect (no --source) was accepted")
	}
	for _, want := range []string{"--source", "cloud", "doubletick", "self-managed"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("missing-source error = %q, want it to mention %q", err, want)
		}
	}
}

func TestConnectRejectsUnknownSource(t *testing.T) {
	opts, err := parseConnectOptions("connect", []string{"--source", "direct"})
	if err != nil {
		t.Fatalf("parseConnectOptions: %v", err)
	}
	err = validateConnectSource(opts)
	if err == nil {
		t.Fatal("an unknown --source value was accepted")
	}
	for _, want := range []string{"cloud", "doubletick", "self-managed"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("invalid-source error = %q, want it to list %q", err, want)
		}
	}
}

func TestConnectRejectsFlagsThatDoNotApplyToTheSelectedSource(t *testing.T) {
	cases := [][]string{
		{"--source", "cloud", "--port", "61012"},
		{"--source", "cloud", "--acknowledge-ban-risk"},
		{"--source", "doubletick", "--phone", "+393481234567"},
		{"--source", "self-managed", "--opener", "hello"},
	}
	for _, args := range cases {
		opts, err := parseConnectOptions("connect", args)
		if err != nil {
			t.Fatalf("parseConnectOptions(%q): %v", args, err)
		}
		if err := validateConnectSource(opts); err == nil {
			t.Errorf("validateConnectSource(%q) accepted a flag that does not apply to the source", args)
		}
	}
}

// TestResolveConnectRoutesEachSource pins the environment gate and the internal path
// each source resolves to, without a daemon, socket, or network.
func TestResolveConnectRoutesEachSource(t *testing.T) {
	cloudCfg := managedConfig{cloudManaged: true, vestadBase: "https://box:8443", agentName: "alice", agentToken: "atok"}
	directCfg := managedConfig{directURL: "https://doubletick.example", directKey: "wak_x"}

	cloudRoute, err := resolveConnect(connectOptions{source: sourceCloud, opener: "hi"}, cloudCfg)
	if err != nil {
		t.Fatalf("cloud resolve: %v", err)
	}
	if !cloudRoute.provision || !cloudRoute.forceCloud || cloudRoute.opener != "hi" {
		t.Errorf("cloud route = %+v, want provision+forceCloud with opener", cloudRoute)
	}

	// cloud even when direct creds are also set still forces the cloud auth path.
	cloudWithDirect := cloudCfg
	cloudWithDirect.directURL, cloudWithDirect.directKey = "https://doubletick.example", "wak_x"
	if r, err := resolveConnect(connectOptions{source: sourceCloud}, cloudWithDirect); err != nil || !r.forceCloud {
		t.Errorf("cloud+direct route = %+v err=%v, want forceCloud", r, err)
	}

	dtRoute, err := resolveConnect(connectOptions{source: sourceDoubletick, opener: "yo"}, directCfg)
	if err != nil {
		t.Fatalf("doubletick resolve: %v", err)
	}
	if !dtRoute.provision || dtRoute.forceCloud || dtRoute.opener != "yo" {
		t.Errorf("doubletick route = %+v, want provision without forceCloud", dtRoute)
	}

	qrRoute, err := resolveConnect(connectOptions{source: sourceSelfManaged}, managedConfig{})
	if err != nil {
		t.Fatalf("self-managed resolve: %v", err)
	}
	if qrRoute.provision || qrRoute.linkPhone != "" {
		t.Errorf("self-managed route = %+v, want link", qrRoute)
	}

	phoneRoute, err := resolveConnect(connectOptions{source: sourceSelfManaged, phone: "+393481234567"}, managedConfig{})
	if err != nil {
		t.Fatalf("self-managed phone resolve: %v", err)
	}
	if phoneRoute.linkPhone != "+393481234567" {
		t.Errorf("self-managed phone route = %+v, want linkPhone", phoneRoute)
	}
}

// TestResolveConnectRejectsUnsatisfiableEnvironment pins the environment gates: cloud
// without a cloud box and doubletick without direct creds must error, not fall back.
func TestResolveConnectRejectsUnsatisfiableEnvironment(t *testing.T) {
	if _, err := resolveConnect(connectOptions{source: sourceCloud}, managedConfig{}); err == nil {
		t.Error("--source cloud on a non-cloud box was accepted")
	}
	if _, err := resolveConnect(connectOptions{source: sourceDoubletick}, managedConfig{}); err == nil {
		t.Error("--source doubletick without direct creds was accepted")
	}
}

// TestRunConnectDispatchesToProvisionForCloud verifies the top-level verb routes a
// resolved cloud source to runProvision and drops the direct pool creds first, with
// the network seams mocked so nothing leaves the process.
func TestRunConnectDispatchesToProvisionForCloud(t *testing.T) {
	t.Setenv("DOUBLETICK_API_URL", "https://doubletick.example")
	t.Setenv("DOUBLETICK_API_KEY", "wak_x")
	t.Setenv("AGENT_NAME", "alice")
	t.Setenv("AGENT_TOKEN", "atok")
	t.Setenv("BOX_HOST", "box")
	t.Setenv("VESTAD_PORT", "8443")
	t.Setenv("VESTA_CLOUD_CONTROL_URL", "https://vesta.run/api")

	var gotOpener string
	provisioned := false
	restore := connectProvision
	connectProvision = func(opener string) { provisioned = true; gotOpener = opener }
	t.Cleanup(func() { connectProvision = restore })

	oldArgs := os.Args
	os.Args = []string{"whatsapp", "--source", "cloud", "--opener", "hello"}
	t.Cleanup(func() { os.Args = oldArgs })

	runConnect()

	if !provisioned {
		t.Fatal("cloud connect did not route to runProvision")
	}
	if gotOpener != "hello" {
		t.Errorf("provision opener = %q, want hello", gotOpener)
	}
	if os.Getenv("DOUBLETICK_API_URL") != "" || os.Getenv("DOUBLETICK_API_KEY") != "" {
		t.Error("cloud connect did not drop the direct pool creds before provisioning")
	}
}

// TestRunConnectAliasSkipsSourceRequirement verifies the dev-only provision and link
// aliases route straight to their path without needing --source.
func TestRunConnectAliasSkipsSourceRequirement(t *testing.T) {
	provisioned, linked, phoneLinked := false, false, ""
	rp, rl, rlp := connectProvision, connectLink, connectLinkPhone
	connectProvision = func(string) { provisioned = true }
	connectLink = func() { linked = true }
	connectLinkPhone = func(phone string) { phoneLinked = phone }
	t.Cleanup(func() { connectProvision, connectLink, connectLinkPhone = rp, rl, rlp })

	oldArgs := os.Args
	t.Cleanup(func() { os.Args = oldArgs })

	os.Args = []string{"whatsapp"}
	runConnectAlias("provision", true)
	if !provisioned {
		t.Error("provision alias did not route to runProvision")
	}

	os.Args = []string{"whatsapp"}
	runConnectAlias("link", false)
	if !linked {
		t.Error("link alias did not route to runLink")
	}

	os.Args = []string{"whatsapp", "--phone", "+393481234567"}
	runConnectAlias("link", false)
	if phoneLinked != "+393481234567" {
		t.Errorf("link --phone alias routed to %q, want the phone pairing path", phoneLinked)
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
