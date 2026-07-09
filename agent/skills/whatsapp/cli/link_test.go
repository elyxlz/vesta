package main

import "testing"

func TestLinkPageURL(t *testing.T) {
	cases := []struct {
		tunnel, agent string
		port          int
		want          string
	}{
		{"https://foo.vesta.run", "gianfranco", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link/"},
		{"https://foo.vesta.run/", "gianfranco", 8811, "https://foo.vesta.run/agents/gianfranco/wa-link/"},
		{"", "gianfranco", 8811, "http://localhost:8811/"},
		{"", "", 8811, "http://localhost:8811/"},
	}
	for _, tc := range cases {
		if got := linkPageURL(tc.tunnel, tc.agent, tc.port); got != tc.want {
			t.Errorf("linkPageURL(%q,%q,%d) = %q, want %q", tc.tunnel, tc.agent, tc.port, got, tc.want)
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
