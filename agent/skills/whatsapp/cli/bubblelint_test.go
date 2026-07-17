package main

import "testing"

// TestBubbleLintPasses pins the sends that must reach the recipient untouched:
// short bubbles, one sentence, and the protected spans (urls, decimals,
// initialisms, abbreviations) whose dots must not read as sentence breaks.
func TestBubbleLintPasses(t *testing.T) {
	cases := []string{
		"nope, nothing",
		"on it",
		"yep",
		"checked both folders, nothing from them either",
		"running late, see you at 8",                    // a decimal-free single thought
		"meet at 8.30 by the door",                      // decimal must not split into two sentences
		"the W.A.S.T.E. system is down",                 // initialism protected
		"see https://example.com/a.b.c for the details", // url protected
		"call Dr. Smith back today",                     // abbreviation protected
		"done, anything else?",                          // single sentence is allowed
	}
	for _, msg := range cases {
		if reason := bubbleLintReason(msg); reason != "" {
			t.Errorf("bubbleLintReason(%q) = %q, want pass", msg, reason)
		}
	}
}

// TestBubbleLintBlocks pins the walls that must be rejected so the agent re-sends
// as several short bubbles.
func TestBubbleLintBlocks(t *testing.T) {
	cases := []struct {
		name string
		msg  string
	}{
		{"two sentences in one bubble", "done. anything else?"},
		{"three sentences in one bubble", "i checked the first folder. then the second one. nothing in either."},
		{"long single sentence", "so the thing about the deploy is that it kept timing out on the build step and i had to bump the worker memory and also tweak the cache config and re-run it twice and then clear the layer cache before it finally went green for us this afternoon"},
	}
	for _, c := range cases {
		if reason := bubbleLintReason(c.msg); reason == "" {
			t.Errorf("%s: bubbleLintReason(%q) passed, want a block reason", c.name, c.msg)
		}
	}
}

// TestCountSentences pins the sentence counter directly, including the protected
// spans that must not inflate the count.
func TestCountSentences(t *testing.T) {
	cases := []struct {
		msg  string
		want int
	}{
		{"one thought", 0},
		{"one thought.", 1},
		{"first. second.", 2},
		{"first. second. third.", 3},
		{"meet at 8.30 sharp", 0},
		{"the U.K. office opens at 9", 0},
		{"check https://a.com/x.y now", 0},
		{"e.g. this should not count", 0},
	}
	for _, c := range cases {
		if got := countSentences(c.msg); got != c.want {
			t.Errorf("countSentences(%q) = %d, want %d", c.msg, got, c.want)
		}
	}
}
