package main

// Bubble lint: catch wall-of-text chat sends before they reach the recipient.
//
// Why this lives in the CLI: the "text in short bubbles, one thought per send"
// rule lived only in the personality preset, a rule the agent had to remember to
// enact on every message, and it kept regressing into one multi-sentence block
// that reads like an assistant, not a person. A rule that must be remembered is
// the weakest enforcement. Checking at send time, in the one place every send
// passes through, makes it structural: a wall is rejected with the reason, so the
// agent re-sends as several short calls and chooses its own break points (it
// trains the behaviour rather than mechanically chunking the text).
//
// The single bypass is the `--longform` flag, for genuine reference material the
// user asked for (a brief, a code block, a list). It is deliberately the only
// escape hatch: routing a wall through `--message-file` is exactly the regression
// this guards against, so file-sourced sends are linted too.

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
	bubbleAbbrRe       = regexp.MustCompile(`(?i)\b(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|a\.m|p\.m|u\.k|u\.s|approx|no|fig)\.`)
	bubbleEllipsisRe   = regexp.MustCompile(`\.{3,}`) // ellipsis: a texting beat, not a full stop
	bubbleEnderRe      = regexp.MustCompile(`[.!?]+`)
)

// stripProtected blanks out spans whose '.', '?' or '!' are not full stops, so
// they cannot trip the lint.
func stripProtected(text string) string {
	for _, re := range []*regexp.Regexp{bubbleURLRe, bubbleDecimalRe, bubbleInitialismRe, bubbleAbbrRe, bubbleEllipsisRe} {
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
