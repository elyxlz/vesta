#!/usr/bin/env python3
"""Regression tests for transcript scanning in redact_secrets.py.

Why this feature exists, and why it is DETECT-ONLY:

Every probe in redact_secrets.py took its scope as an INPUT: a hardcoded list of SQLite stores. An
artefact nobody thought to list was therefore invisible to the entire scanner by construction. The
session transcript is exactly that artefact. It is JSONL, not SQLite, so no line of the store code
could see it, and "No secrets found." was only ever a statement about the databases. On the box
where this was written, a real agent token sat in the transcript in several places while events.db
was genuinely clean and the scanner correctly said so.

The asymmetry is deliberate: transcripts are detected, never scrubbed. The file is held open for
append by the running session, so rewriting it races the live writer. The remedy for a credential in
a transcript is to ROTATE THE CREDENTIAL, which invalidates every copy everywhere. A file edit only
moves the problem and feels like a fix.

The two tests that matter most, and why:
  - `zero budget -> TRUNCATED`. A detector that reports a half-read file as clean is the exact false
    negative the scanner exists to prevent, and it looks healthy the whole time.
  - the healthy case. Replaying only the failure proves a check FIRES; it does not prove it can tell
    the difference. So a clean file must be positively reported as scanned-with-zero-hits, not
    silently omitted.

Run it directly: python3 test_redact_transcripts.py
"""

import contextlib
import io
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import redact_secrets

# A syntactically valid but entirely fake credential. Long hex run, matches the token shape.
FAKE_TOKEN = "deadbeefcafe1234567890abcdef1234567890abcdef1234567890abcdef1234"

CLEAN = '{"type":"user","text":"hello there nothing here"}\n{"type":"assistant","text":"also clean"}\n'
# Line 2 is deliberately MALFORMED JSON. The live session's final line is often a partial append,
# and that is precisely where the newest secret would sit, so the raw-line fallback must catch it.
DIRTY = '{"type":"user","text":"export AGENT_TOKEN=' + FAKE_TOKEN + '"}\n{"broken json line with password="hunter2supersecret"\n'


def main() -> int:
    failures = 0

    def check(name: str, condition: bool) -> None:
        nonlocal failures
        print(("  ok   " if condition else "  FAIL ") + name)
        if not condition:
            failures += 1

    original_roots = redact_secrets.TRANSCRIPT_ROOTS
    original_budget = redact_secrets.TRANSCRIPT_SCAN_BUDGET_SECS
    try:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            project = root / "proj"
            project.mkdir()
            (project / "clean.jsonl").write_text(CLEAN)
            (project / "dirty.jsonl").write_text(DIRTY)

            # --- scope discovery -------------------------------------------------------------
            redact_secrets.TRANSCRIPT_ROOTS = (root / "nope",)
            check("absent root -> transcript_files() empty", redact_secrets.transcript_files() == [])
            check("absent root -> scan_transcripts() empty", redact_secrets.scan_transcripts() == [])

            redact_secrets.TRANSCRIPT_ROOTS = (root,)
            redact_secrets.TRANSCRIPT_SCAN_BUDGET_SECS = 60
            check("both transcripts discovered by glob", len(redact_secrets.transcript_files()) == 2)

            reports = {report.store.path.name: report for report in redact_secrets.scan_transcripts()}

            # --- the HEALTHY case ------------------------------------------------------------
            check("clean file is reported, not omitted", "clean.jsonl" in reports)
            check("clean file has zero hits", not reports["clean.jsonl"].hits)
            check("clean file status says scanned", reports["clean.jsonl"].status.startswith("scanned"))

            # --- detection -------------------------------------------------------------------
            dirty = reports["dirty.jsonl"]
            check("dirty file finds both secrets", len(dirty.hits) == 2)
            check("valid-JSON line detected", any(ref.endswith(":1") for ref, _ in dirty.hits))
            check("MALFORMED line detected via raw fallback", any(ref.endswith(":2") for ref, _ in dirty.hits))
            check("refs are namespaced transcript/", all(ref.startswith("transcript/") for ref, _ in dirty.hits))

            # --- masking: the scanner must never reprint the secret --------------------------
            check("raw secret never appears in output", not any(FAKE_TOKEN in s for _, s in dirty.hits))
            check("snippets are masked", all(redact_secrets.REDACTED in s for _, s in dirty.hits))

            # --- truncation must never look clean --------------------------------------------
            redact_secrets.TRANSCRIPT_SCAN_BUDGET_SECS = -1
            truncated = redact_secrets.scan_transcripts()[0]
            check("over-budget reports TRUNCATED", "TRUNCATED" in truncated.status)
            check(
                "TRUNCATED is not 'scanned'/'absent', so _run_scan lists it as partial coverage",
                not truncated.status.startswith(("scanned", "absent")),
            )

        # --- scrub must refuse transcripts, before ref parsing ------------------------------
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = redact_secrets._run_scrub(["transcript/proj/dirty.jsonl:1"])
        message = stderr.getvalue()
        check("scrub of a transcript ref exits 1", code == 1)
        check("refusal names the real remedy (rotation)", "Rotate the credential" in message)
        check("refusal fires BEFORE the ref parser", "bad reference" not in message)
    finally:
        redact_secrets.TRANSCRIPT_ROOTS = original_roots
        redact_secrets.TRANSCRIPT_SCAN_BUDGET_SECS = original_budget

    print(f"\n{'ALL PASS' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
