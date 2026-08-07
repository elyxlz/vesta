#!/bin/bash
set -euo pipefail

WHISPER_BIN="${WHISPER_BIN:-/usr/local/bin/whisper-cli}"

# Default model: multilingual ggml-small.bin. The fallback chain matches the
# model paths the whatsapp CLI's transcribe.go probes; a box may hold only an
# english-only or tiny model.
DEFAULT_MODEL="/usr/local/share/ggml-small.bin"
resolve_model() {
    for candidate in \
        "$DEFAULT_MODEL" \
        /usr/local/share/ggml-small.en.bin \
        /usr/local/share/ggml-tiny.bin \
        /usr/local/share/ggml-tiny.en.bin
    do
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    echo "$DEFAULT_MODEL"
}
WHISPER_MODEL="${WHISPER_MODEL:-$(resolve_model)}"

# Auto-detect per file unless WHISPER_LANGUAGE pins one whisper.cpp language code;
# --language overrides either. Same variable the whatsapp CLI reads.
LANGUAGE="${WHISPER_LANGUAGE:-auto}"

usage() {
    echo "Usage: whisper_transcribe.sh <audio-file> [options]"
    echo ""
    echo "Options:"
    echo "  --model <path>     Model file (default: $WHISPER_MODEL)"
    echo "  --language <lang>  Language code, e.g. en, es, fr (default: $LANGUAGE)"
    echo "  --translate        Translate to English"
    echo "  --srt              Output SRT subtitles instead of plain text"
    echo "  --json             Output JSON with timestamps"
    echo "  --threads <n>      Number of threads (default: 4)"
    exit 1
}

if [ $# -lt 1 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    usage
fi

INPUT_FILE="$1"
shift

if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: file not found: $INPUT_FILE" >&2
    exit 1
fi

TRANSLATE=""
OUTPUT_FORMAT=""
THREADS="4"

while [ $# -gt 0 ]; do
    case "$1" in
        --model) WHISPER_MODEL="$2"; shift 2 ;;
        --language) LANGUAGE="$2"; shift 2 ;;
        --translate) TRANSLATE="-tr"; shift ;;
        --srt) OUTPUT_FORMAT="srt"; shift ;;
        --json) OUTPUT_FORMAT="json"; shift ;;
        --threads) THREADS="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "$WHISPER_BIN" ]; then
    echo "Error: whisper-cli not found at $WHISPER_BIN" >&2
    echo "Run the setup commands from the whisper SKILL.md first." >&2
    exit 1
fi

if [ ! -f "$WHISPER_MODEL" ]; then
    echo "Error: model not found at $WHISPER_MODEL" >&2
    echo "Download it: curl -L -o $WHISPER_MODEL https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$(basename "$WHISPER_MODEL")" >&2
    exit 1
fi

TMP_WAV=$(mktemp /tmp/whisper_XXXX.wav)
TMP_OUT=$(mktemp /tmp/whisper_out_XXXX)
TMP_ERR=$(mktemp /tmp/whisper_err_XXXX)
trap 'rm -f "$TMP_WAV" "$TMP_OUT" "${TMP_OUT}.srt" "${TMP_OUT}.json" "$TMP_ERR"' EXIT

# whisper.cpp writes its progress banner to stderr, but also real diagnostics,
# e.g. "model is not multilingual, ignoring language and translation options"
# when an .en model silently drops --language/--translate. Keep the banner
# quiet, forward warnings and errors, and dump all of stderr on a failed run.
run_whisper() {
    local status=0
    "$WHISPER_BIN" "$@" 2>"$TMP_ERR" || status=$?
    if [ "$status" -ne 0 ]; then
        cat "$TMP_ERR" >&2
        exit "$status"
    fi
    grep -iE 'warning|^error:|failed' "$TMP_ERR" >&2 || true
}

ffmpeg -i "$INPUT_FILE" -ar 16000 -ac 1 -c:a pcm_s16le "$TMP_WAV" -y 2>/dev/null

ARGS=(-m "$WHISPER_MODEL" -f "$TMP_WAV" -l "$LANGUAGE" -t "$THREADS")
if [ -n "$TRANSLATE" ]; then
    ARGS+=("$TRANSLATE")
fi

if [ -n "$OUTPUT_FORMAT" ]; then
    case "$OUTPUT_FORMAT" in
        srt)  ARGS+=(-osrt -of "$TMP_OUT") ;;
        json) ARGS+=(-oj -of "$TMP_OUT") ;;
    esac
    run_whisper "${ARGS[@]}" >/dev/null
    cat "${TMP_OUT}.${OUTPUT_FORMAT}"
else
    ARGS+=(--no-timestamps)
    run_whisper "${ARGS[@]}"
fi
