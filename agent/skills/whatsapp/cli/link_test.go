package main

import (
	"os"
	"reflect"
	"testing"
)

func TestLinkServeArgs(t *testing.T) {
	savedArgs := os.Args
	defer func() { os.Args = savedArgs }()

	cases := []struct {
		name string
		args []string
		want []string
	}{
		{"no instance flag", []string{"whatsapp", "link"}, nil},
		{"instance flag", []string{"whatsapp", "link", "--instance", "personal"}, []string{"--instance", "personal"}},
		{"instance flag with =", []string{"whatsapp", "link", "--instance=personal"}, []string{"--instance", "personal"}},
	}
	for _, tc := range cases {
		os.Args = tc.args
		if got := linkServeArgs(); !reflect.DeepEqual(got, tc.want) {
			t.Errorf("%s: linkServeArgs() = %#v, want %#v", tc.name, got, tc.want)
		}
	}
}

func TestLinkPageURL(t *testing.T) {
	cases := []struct {
		tunnel, agent, service string
		port                   int
		want                   string
	}{
		{"https://foo.vesta.run", "gianfranco", "wa-link", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link/"},
		{"https://foo.vesta.run/", "gianfranco", "wa-link", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link/"},
		{"https://foo.vesta.run", "gianfranco", "wa-link-personal", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link-personal/"},
		{"", "gianfranco", "wa-link", 8811, "http://localhost:8811/"},
		{"", "", "wa-link", 8811, "http://localhost:8811/"},
	}
	for _, tc := range cases {
		if got := linkPageURL(tc.tunnel, tc.agent, tc.service, tc.port); got != tc.want {
			t.Errorf("linkPageURL(%q,%q,%q,%d) = %q, want %q", tc.tunnel, tc.agent, tc.service, tc.port, got, tc.want)
		}
	}
}

func TestParsePortFlag(t *testing.T) {
	cases := []struct {
		value   string
		want    int
		wantErr bool
	}{
		{"", 0, false},
		{"8080", 8080, false},
		{"65535", 65535, false},
		{"0", 0, false},
		{"bad", 0, true},
		{"65536", 0, true},
		{"-1", 0, true},
	}
	for _, tc := range cases {
		got, err := parsePortFlag(tc.value)
		if (err != nil) != tc.wantErr {
			t.Errorf("parsePortFlag(%q) error = %v, wantErr %v", tc.value, err, tc.wantErr)
		}
		if err == nil && got != tc.want {
			t.Errorf("parsePortFlag(%q) = %d, want %d", tc.value, got, tc.want)
		}
	}
}
