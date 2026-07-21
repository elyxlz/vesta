package main

// Bubble lint: catch wall-of-text chat sends before they reach the recipient.
// The "text in short bubbles, one thought per send" rule is enforced here at
// send time rather than left to the personality preset: a rule the agent must
// remember to apply is the weakest enforcement and regresses into blocks that
// read like an assistant, not a person. Linting the one place every send passes
// through makes it structural: a wall is rejected with the reason, so the agent
// re-sends as several short calls with its own break points. The single bypass
// is `--longform` (reference material the user asked for); `--message-file` sends are linted too.

import (
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"
)

// A bubble is "a few words to one line, rarely two" (personality SKILL.md).
const (
	bubbleMaxChars = 220           // a genuinely long single bubble
	bubbleSpace    = " \t\r\n\v\f" // the gap that makes a mark read as a full stop
)

var (
	bubbleURLRe        = regexp.MustCompile(`https?://\S+`)         // urls
	bubbleDecimalRe    = regexp.MustCompile(`\b\d+[.,]\d+\b`)       // decimals: 8.6, 86,5
	bubbleInitialismRe = regexp.MustCompile(`\b(?:[A-Za-z]\.){2,}`) // initialisms: W.A.S.T.E., U.K.
	// Abbreviations, an allowlist, so an unlisted one reads as a full stop. Every entry is a word
	// that is always followed by more, never one that can end a thought: protecting "etc." or "min."
	// would blank the stop in "eggs, milk, etc. also bread" and let the wall through. Dotted forms
	// (e.g., a.m., U.K.) are absent because bubbleInitialismRe already covers them.
	bubbleAbbrRe = regexp.MustCompile(`(?i)\b(?:mr|mrs|ms|dr|prof|jr|sr|st|vs|approx|fig` +
		`|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec` +
		`|inc|ltd|co|corp|ave|rd|blvd|vol|ch|pp)\.`)
	bubbleEllipsisRe = regexp.MustCompile(`\.{3,}`) // ellipsis: a texting beat, not a full stop
	// A line-leading ordered-list marker ("1.", "2)") is not a full stop: each item is one
	// short thought. Only the marker is blanked, so a real wall inside an item still trips.
	bubbleListMarkerRe = regexp.MustCompile(`(?m)^[ \t]*\d+[.)][ \t]`)
	bubbleEnderRe      = regexp.MustCompile(`[.!?]+`)
)

// stripProtected blanks out spans whose '.', '?' or '!' are not full stops, so
// they cannot trip the lint.
func stripProtected(text string) string {
	for _, re := range []*regexp.Regexp{bubbleListMarkerRe, bubbleURLRe, bubbleDecimalRe, bubbleInitialismRe, bubbleAbbrRe, bubbleEllipsisRe} {
		text = re.ReplaceAllString(text, " ")
	}
	return text
}

// textAfterFullStop reports whether a '.', '!' or '?' has anything after it: the
// tell of a second thought crammed into the same bubble. A mark only reads as a
// full stop when whitespace follows it, so "main.py" and "example.com" stay
// single thoughts.
func textAfterFullStop(text string) bool {
	cleaned := strings.TrimSpace(stripProtected(text))
	for _, loc := range bubbleEnderRe.FindAllStringIndex(cleaned, -1) {
		rest := cleaned[loc[1]:]
		trimmed := strings.TrimLeft(rest, bubbleSpace)
		if trimmed == "" || len(trimmed) == len(rest) {
			continue // the mark ends the bubble, or no whitespace gap follows it
		}
		return true
	}
	return false
}

// bubbleLintReason returns a non-empty explanation when message is a wall (too
// many characters, or text carrying on past a full stop), or "" if it passes.
// The caller turns a non-empty reason into an error that blocks the send.
func bubbleLintReason(message string) string {
	nChars := utf8.RuneCountInString(message)
	var why []string
	if nChars > bubbleMaxChars {
		why = append(why, fmt.Sprintf("%d chars", nChars))
	}
	if textAfterFullStop(message) {
		why = append(why, "text after a full stop")
	}
	if len(why) == 0 {
		return ""
	}
	return "bubble lint: this send is a wall (" + strings.Join(why, ", ") + "). " +
		"texting rule: short bubbles, one thought per send, and don't use full stops at all. " +
		"split it into several separate send calls, a beat between each, one idea each. if this " +
		"is genuine reference material (a brief, a code block, a list they asked for), resend the " +
		"same command with --longform to bypass."
}
