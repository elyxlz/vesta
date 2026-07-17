package main

import "testing"

// TestBubbleLintPasses pins the sends that must reach the recipient untouched:
// short bubbles that end at their one mark (or carry none at all), and the
// protected spans (urls, decimals, initialisms, abbreviations, ellipses) whose
// dots must not read as full stops.
func TestBubbleLintPasses(t *testing.T) {
	cases := []string{
		"nope, nothing",
		"on it",
		"yep",
		"checked both folders, nothing from them either",
		"running late, see you at 8",
		"done, anything else?",                          // a trailing mark ends the bubble
		"one thought.",                                  // a trailing full stop ends the bubble
		"meet at 8.30 by the door",                      // decimal must not read as a full stop
		"the W.A.S.T.E. system is down",                 // initialism protected
		"see https://example.com/a.b.c for the details", // url protected
		"call Dr. Smith back today",                     // abbreviation protected
		"meet on Jan. 5",                                // month abbreviation protected
		"call Acme Inc. tomorrow",                       // company abbreviation protected
		"it's on Oxford Ave. somewhere",                 // street abbreviation protected
		"ask Jr. about it",                              // name suffix protected
		"see vol. 3 for that",                           // reference abbreviation protected
		"wait... what",                                  // ellipsis is a beat, not a full stop
		"hmm... ok",                                     // ellipsis is a beat, not a full stop
		"it's in main.py",                               // no whitespace gap, so not a full stop
		"check example.com later",                       // no whitespace gap, so not a full stop
	}
	for _, msg := range cases {
		if reason := bubbleLintReason(msg); reason != "" {
			t.Errorf("bubbleLintReason(%q) = %q, want pass", msg, reason)
		}
	}
}

// TestBubbleLintBlocks pins the walls that must be rejected so the agent re-sends
// as several short bubbles. Anything past a full stop is a second thought.
func TestBubbleLintBlocks(t *testing.T) {
	cases := []struct {
		name string
		msg  string
	}{
		{"text after a full stop", "hey. ok"},
		{"two sentences in one bubble", "done. anything else?"},
		{"three sentences in one bubble", "i checked the first folder. then the second one. nothing in either."},
		{"text after a question mark", "hey! how are you?"},
		{"text after an exclamation mark", "nice! on it"},
		{"ellipsis does not license a later full stop", "wait... what. ok"},
		// An abbreviation that can end a thought would hide these walls, so none is protected.
		{"no. is not protected", "the answer is no. anyway i tried"},
		{"etc. is not protected", "eggs, milk, etc. also bread"},
		{"sec. is not protected", "one sec. i'll check"},
		{"min. is not protected", "takes 20 min. i'll wait"},
		{"long single sentence", "so the thing about the deploy is that it kept timing out on the build step and i had to bump the worker memory and also tweak the cache config and re-run it twice and then clear the layer cache before it finally went green for us this afternoon"},
	}
	for _, c := range cases {
		if reason := bubbleLintReason(c.msg); reason == "" {
			t.Errorf("%s: bubbleLintReason(%q) passed, want a block reason", c.name, c.msg)
		}
	}
}

// TestTextAfterFullStop pins the detector directly, including the protected
// spans that must not read as full stops.
func TestTextAfterFullStop(t *testing.T) {
	cases := []struct {
		msg  string
		want bool
	}{
		{"one thought", false},
		{"one thought.", false},
		{"hey. ok", true},
		{"first. second.", true},
		{"first. second. third.", true},
		{"meet at 8.30 sharp", false},
		{"the U.K. office opens at 9", false},
		{"check https://a.com/x.y now", false},
		{"e.g. this should not count", false},
		{"wait... what", false},
		{"wait...", false},
	}
	for _, c := range cases {
		if got := textAfterFullStop(c.msg); got != c.want {
			t.Errorf("textAfterFullStop(%q) = %v, want %v", c.msg, got, c.want)
		}
	}
}
