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
