package main

import (
	"strings"
	"testing"
)

// TestToMarkdownV2PreservesBareStripeURL pins the original bug: a bare
// `cs_live_...` checkout URL had its underscores eaten by legacy Markdown
// (parsed as italics), corrupting the Stripe session id -> a dead pay page.
// Under MarkdownV2 every underscore is backslash-escaped, so Telegram renders
// the literal character and the id survives; Telegram then auto-links the URL.
func TestToMarkdownV2PreservesBareStripeURL(t *testing.T) {
	in := "Pay here: https://checkout.stripe.com/c/pay/cs_live_a1IUB9_c3"
	out := toMarkdownV2(in)
	if !strings.Contains(out, `cs\_live\_a1IUB9\_c3`) {
		t.Fatalf("underscores not escaped, id would be corrupted: %q", out)
	}
	// A bare URL is not a Markdown link, so brackets/parens are absent.
	if strings.Contains(out, "](") {
		t.Fatalf("bare URL should not become a link construct: %q", out)
	}
}

// TestToMarkdownV2PreservesMarkdownLink verifies an explicit [label](url) link
// is kept intact -- label escaped as text, URL byte-for-byte inside the
// destination -- so the onboard skill can hand out a real clickable pay link
// whose session id is not mangled.
func TestToMarkdownV2PreservesMarkdownLink(t *testing.T) {
	url := "https://checkout.stripe.com/c/pay/cs_live_a1IUB9"
	in := "[Complete your payment](" + url + ")"
	out := toMarkdownV2(in)
	want := "[Complete your payment](" + url + ")"
	if out != want {
		t.Fatalf("link not preserved:\n got %q\nwant %q", out, want)
	}
}

// TestToMarkdownV2EscapesReservedSpecials checks a run of literal specials is
// fully escaped so Telegram never rejects the message or drops characters.
func TestToMarkdownV2EscapesReservedSpecials(t *testing.T) {
	if out := toMarkdownV2("2+2=4."); out != `2\+2\=4\.` {
		t.Fatalf("reserved specials not escaped: %q", out)
	}
}

// TestToMarkdownV2LabelSpecialsEscaped ensures special characters inside a
// link label are escaped (only the URL destination is exempt), so a label
// can't break MarkdownV2 parsing.
func TestToMarkdownV2LabelSpecialsEscaped(t *testing.T) {
	out := toMarkdownV2("[pay now!](https://example.com/x)")
	if !strings.Contains(out, `[pay now\!]`) {
		t.Fatalf("label specials not escaped: %q", out)
	}
	if !strings.Contains(out, "](https://example.com/x)") {
		t.Fatalf("url destination not preserved: %q", out)
	}
}
