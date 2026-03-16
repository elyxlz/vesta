#!/bin/bash
set -euo pipefail

WHISPER_BIN="${WHISPER_BIN:-/usr/local/bin/whisper-cli}"
WHISPER_MODEL="${WHISPER_MODEL:-/usr/local/share/ggml-small.en.bin}"

usage() {
    echo "Usage: whisper_transcribe.sh <audio-file> [options]"
    echo ""
    echo "Options:"
    echo "  --model <path>     Model file (default: $WHISPER_MODEL)"
    echo "  --language <lang>  Language code, e.g. en, es, fr (default: en)"
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

LANGUAGE="en"
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
    echo "Download it: curl -L -o $WHISPER_MODEL https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin" >&2
    exit 1
fi

TMP_WAV=$(mktemp /tmp/whisper_XXXX.wav)
TMP_OUT=$(mktemp /tmp/whisper_out_XXXX)
trap "rm -f $TMP_WAV $TMP_OUT ${TMP_OUT}.srt ${TMP_OUT}.json" EXIT

ffmpeg -i "$INPUT_FILE" -ar 16000 -ac 1 -c:a pcm_s16le "$TMP_WAV" -y 2>/dev/null

ARGS=(-m "$WHISPER_MODEL" -f "$TMP_WAV" -l "$LANGUAGE" -t "$THREADS" $TRANSLATE)

if [ -n "$OUTPUT_FORMAT" ]; then
    case "$OUTPUT_FORMAT" in
        srt)  ARGS+=(-osrt -of "$TMP_OUT") ;;
        json) ARGS+=(-oj -of "$TMP_OUT") ;;
    esac
    "$WHISPER_BIN" "${ARGS[@]}" >/dev/null 2>/dev/null
    cat "${TMP_OUT}.${OUTPUT_FORMAT}"
else
    ARGS+=(--no-timestamps)
    "$WHISPER_BIN" "${ARGS[@]}" 2>/dev/null
fi
