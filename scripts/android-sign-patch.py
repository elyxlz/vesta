#!/usr/bin/env python3
"""Patch Tauri-generated Android build.gradle.kts to add release signing.

Expects a `keystore.properties` file next to `gen/android/` with:
    storePassword=...
    keyPassword=...
    keyAlias=...
    storeFile=<absolute path to .jks>

Idempotent: running twice is a no-op.
"""

import pathlib
import re
import sys

IMPORTS_BLOCK = """import java.io.FileInputStream
import java.util.Properties

"""

KEYSTORE_LOAD_BLOCK = """
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

"""

SIGNING_CONFIGS_BLOCK = """    signingConfigs {
        create("release") {
            keyAlias = keystoreProperties.getProperty("keyAlias")
            keyPassword = keystoreProperties.getProperty("keyPassword")
            storeFile = file(keystoreProperties.getProperty("storeFile"))
            storePassword = keystoreProperties.getProperty("storePassword")
        }
    }

"""

RELEASE_SIGNING_LINE = '            signingConfig = signingConfigs.getByName("release")\n'

SENTINEL = "signingConfigs.getByName(\"release\")"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: android-sign-patch.py <path to build.gradle.kts>")
    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"file not found: {path}")

    text = path.read_text()
    if SENTINEL in text:
        print(f"{path}: already patched")
        return

    # 1a. Add imports at the very top. Kotlin DSL requires them before `plugins {}`
    #     and does not auto-qualify java.util.* / java.io.*.
    text = IMPORTS_BLOCK + text

    # 1b. Insert keystore loader before the top-level `android {` block.
    android_block = re.search(r"(?m)^android\s*\{", text)
    if not android_block:
        sys.exit("could not find 'android {' block")
    text = text[: android_block.start()] + KEYSTORE_LOAD_BLOCK + text[android_block.start() :]

    # 2. Inject signingConfigs as the first child of `android { }`.
    android_open = re.search(r"(?m)^android\s*\{[ \t]*\n", text)
    if not android_open:
        sys.exit("could not re-locate 'android {' after patch step 1")
    text = text[: android_open.end()] + SIGNING_CONFIGS_BLOCK + text[android_open.end() :]

    # 3. Add signingConfig assignment inside the release buildType.
    release_block = re.search(r'getByName\("release"\)\s*\{[ \t]*\n', text)
    if not release_block:
        sys.exit("could not find 'getByName(\"release\")' block in buildTypes")
    text = text[: release_block.end()] + RELEASE_SIGNING_LINE + text[release_block.end() :]

    path.write_text(text)
    print(f"{path}: patched")


if __name__ == "__main__":
    main()
