"""Mask high-risk personal identifiers at the mail-read boundary.

An agent cannot un-see what a tool prints. Mail search results and notification
previews carry arbitrary third-party text, so an identifier in a snippet enters
the agent's context, its transcript and its event store before any judgement
about whether to record it is possible. Masking here is the only point where
that is preventable: by the time the agent is deciding what to write down, the
value is already stored.

Scope is deliberately narrow: identifiers that are PERMANENT and cannot be
rotated, where a leaked copy stays valuable for life and no remedy converges.
A UK National Insurance number is the type case. Passwords, tokens and card
numbers are out of scope here precisely because they CAN be rotated, and
because a mail body is not where they usually live.

False positives are accepted on purpose. Masking a string that merely looks
like an identifier costs a few characters of a preview; ingesting a real one
costs a permanent identifier sitting in append-only local stores.
"""

import re

# UK National Insurance number.
#
# Case-sensitive by design (the `(?-i:` group survives a case-insensitive outer
# flag): a lowercase run of letters and digits in ordinary prose is not an NI
# number, and matching case-insensitively turns this into a common-word hazard.
#
# The letter classes encode the real allocation rules rather than [A-Z]: the
# first letter excludes D, F, I, Q, U and V; the second additionally excludes O.
# Separators are optional so both "QQ123456A" and "QQ 12 34 56 A" match.
_NI_NUMBER = re.compile(r"(?-i:\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b)")

NI_PLACEHOLDER = "[NI-REDACTED]"


def mask_identifiers(text: str) -> str:
    """Replace permanent personal identifiers in ``text`` with a placeholder.

    Idempotent: the placeholder contains no digits, so a re-run cannot match or
    mangle text that was already masked. Returns the input unchanged when it is
    empty or not a string, so every caller can apply it unconditionally.
    """
    if not text or not isinstance(text, str):
        return text
    return _NI_NUMBER.sub(NI_PLACEHOLDER, text)
