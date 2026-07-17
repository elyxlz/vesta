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
	"unicode"
	"unicode/utf8"
)

// A bubble is "a few words to one line, rarely two" (personality SKILL.md).
const (
	bubbleMaxChars     = 220 // a genuinely long single bubble
	bubbleMaxSentences = 1   // 2+ sentence-enders in one send = a paragraph, split it
)

var (
	bubbleURLRe        = regexp.MustCompile(`https?://\S+`)         // urls
	bubbleDecimalRe    = regexp.MustCompile(`\b\d+[.,]\d+\b`)       // decimals: 8.6, 86,5
	bubbleInitialismRe = regexp.MustCompile(`\b(?:[A-Za-z]\.){2,}`) // initialisms: W.A.S.T.E., U.K.
	bubbleAbbrRe       = regexp.MustCompile(`(?i)\b(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|a\.m|p\.m|u\.k|u\.s|approx|no|fig)\.`)
	bubbleEnderRe      = regexp.MustCompile(`[.!?]+`)
)

// stripProtected blanks out spans whose '.', '?' or '!' are not sentence
// boundaries, so they do not inflate the sentence count.
func stripProtected(text string) string {
	for _, re := range []*regexp.Regexp{bubbleURLRe, bubbleDecimalRe, bubbleInitialismRe, bubbleAbbrRe} {
		text = re.ReplaceAllString(text, " ")
	}
	return text
}

// countSentences counts sentence-ending runs: terminal punctuation followed by
// whitespace and then an ASCII alphanumeric, or sitting at the end of the text.
func countSentences(text string) int {
	cleaned := strings.TrimSpace(stripProtected(text))
	count := 0
	for _, loc := range bubbleEnderRe.FindAllStringIndex(cleaned, -1) {
		rest := cleaned[loc[1]:]
		if rest == "" {
			count++
			continue
		}
		trimmed := strings.TrimLeft(rest, " \t\r\n\v\f")
		if len(trimmed) == len(rest) || trimmed == "" {
			continue // no whitespace gap, or nothing after it
		}
		if r := rune(trimmed[0]); r < utf8.RuneSelf && (unicode.IsLetter(r) || unicode.IsDigit(r)) {
			count++
		}
	}
	return count
}

// bubbleLintReason returns a non-empty explanation when message is a wall (too
// many characters, or too many sentences crammed into one bubble), or "" if it
// passes. The caller turns a non-empty reason into an error that blocks the send.
func bubbleLintReason(message string) string {
	nChars := utf8.RuneCountInString(message)
	nSent := countSentences(message)
	if nChars <= bubbleMaxChars && nSent <= bubbleMaxSentences {
		return ""
	}
	var why []string
	if nChars > bubbleMaxChars {
		why = append(why, fmt.Sprintf("%d chars", nChars))
	}
	if nSent > bubbleMaxSentences {
		why = append(why, fmt.Sprintf("%d sentences in one bubble", nSent))
	}
	return "bubble lint: this send is a wall (" + strings.Join(why, ", ") + "). " +
		"texting rule: short bubbles, one thought per send. split it into several separate send calls, " +
		"a beat between each, one idea each. if this is genuine reference material (a brief, a code block, " +
		"a list they asked for), resend the same command with --longform to bypass."
}
