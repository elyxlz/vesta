#!/usr/bin/env python3
"""Inject Android permissions into the Tauri-generated AndroidManifest.xml.

Tauri's template only declares `INTERNET`. The web app uses getUserMedia for
speech-to-text, which Android WebView won't grant unless the app declares
`RECORD_AUDIO` and `MODIFY_AUDIO_SETTINGS`. wry's RustWebChromeClient already
handles the runtime permission prompt, but that requires the permissions to be
declared in the manifest first.

Idempotent.
"""

import pathlib
import re
import sys

PERMISSIONS = (
    "android.permission.RECORD_AUDIO",
    "android.permission.MODIFY_AUDIO_SETTINGS",
)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: android-add-permissions.py <path to AndroidManifest.xml>")
    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"file not found: {path}")

    text = path.read_text()
    missing = [p for p in PERMISSIONS if p not in text]
    if not missing:
        print(f"{path}: all permissions already declared")
        return

    # Anchor on the existing INTERNET permission line so we inherit its indent
    # and insert right after it.
    anchor = re.search(
        r'^([ \t]*)<uses-permission[^>]*android:name="android\.permission\.INTERNET"[^>]*/>\s*\n',
        text,
        flags=re.MULTILINE,
    )
    if not anchor:
        sys.exit("could not find INTERNET uses-permission line to anchor on")

    indent = anchor.group(1)
    inserted = "".join(f'{indent}<uses-permission android:name="{p}" />\n' for p in missing)
    text = text[: anchor.end()] + inserted + text[anchor.end() :]
    path.write_text(text)
    print(f"{path}: added {', '.join(missing)}")


if __name__ == "__main__":
    main()
