"""Transcribe audiobooks (m4b) to library text JSON using faster-whisper."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AUDIO_DIR = Path.home() / "agent" / "data" / "skills" / "library" / "audio"
TEXT_DIR = Path.home() / "agent" / "data" / "skills" / "library" / "text"

WHISPER_SOCKET = "/tmp/whisper-server.sock"


def get_chapters(audio_path: str) -> list[dict]:
    """Extract chapter metadata from m4b using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_chapters", audio_path],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    chapters = data.get("chapters", [])
    if not chapters:
        # No chapters — treat whole file as one chapter
        duration = float(data["format"]["duration"])
        return [{"title": "Full", "start": 0.0, "end": duration}]
    return [
        {
            "title": ch["tags"].get("title", f"Chapter {i+1}"),
            "start": float(ch["start_time"]),
            "end": float(ch["end_time"]),
        }
        for i, ch in enumerate(chapters)
    ]


def get_metadata(audio_path: str) -> dict:
    """Extract title and author from m4b metadata."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", audio_path],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    tags = data.get("format", {}).get("tags", {})
    return {
        "title": tags.get("title", tags.get("album", Path(audio_path).stem)),
        "author": tags.get("artist", tags.get("album_artist", "Unknown")),
    }


def extract_chapter_audio(audio_path: str, start: float, end: float, out_path: str):
    """Extract a chapter's audio to a wav file."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path,
         "-ss", str(start), "-to", str(end),
         "-ac", "1", "-ar", "16000", "-f", "wav", out_path],
        capture_output=True,
    )


def transcribe_file(audio_path: str) -> str:
    """Transcribe an audio file via the whisper-server Unix socket."""
    import socket as sock

    request = json.dumps({"path": audio_path}).encode()

    s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
    s.connect(WHISPER_SOCKET)
    s.sendall(request)
    s.shutdown(sock.SHUT_WR)

    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()

    result = json.loads(data.decode())
    if result.get("status") != "ok":
        raise RuntimeError(f"Whisper error: {result.get('error', 'unknown')}")

    return result["text"]


def transcribe_book(audio_path: str, output_path: str = None):
    """Transcribe an audiobook and save as library text JSON."""
    audio_path = str(audio_path)
    meta = get_metadata(audio_path)
    chapters = get_chapters(audio_path)

    print(f"\n{'='*60}", flush=True)
    print(f"Book: {meta['title']} by {meta['author']}", flush=True)
    print(f"Chapters: {len(chapters)}", flush=True)
    total_duration = sum(c["end"] - c["start"] for c in chapters)
    print(f"Duration: {total_duration/3600:.1f} hours", flush=True)
    print(f"{'='*60}", flush=True)

    result_chapters = []

    for i, ch in enumerate(chapters):
        duration = ch["end"] - ch["start"]
        print(f"\n  [{i+1}/{len(chapters)}] {ch['title']} ({duration/60:.1f} min)", flush=True)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            extract_chapter_audio(audio_path, ch["start"], ch["end"], tmp.name)
            text = transcribe_file(tmp.name)

        # Format as paragraphs (split on sentence boundaries roughly)
        paragraphs = []
        sentences = text.replace(". ", ".\n").split("\n")
        para = []
        for s in sentences:
            para.append(s.strip())
            if len(para) >= 5:
                paragraphs.append(" ".join(para))
                para = []
        if para:
            paragraphs.append(" ".join(para))

        html = "\n".join(f"<p>{p}</p>" for p in paragraphs)
        result_chapters.append({"title": ch["title"], "html": html})
        print(f"    -> {len(text)} chars transcribed", flush=True)

        # Cool-down pause between chapters
        if i < len(chapters) - 1:
            time.sleep(20)

    # Build output
    book_json = {
        "title": meta["title"],
        "author": meta["author"],
        "chapters": result_chapters,
    }

    # Determine output path
    if not output_path:
        stem = Path(audio_path).stem.replace(" ", "_").replace("-", "_")
        output_path = str(TEXT_DIR / f"{stem}.json")

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(book_json, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved to {output_path}", flush=True)
    return output_path


def main():
    if len(sys.argv) < 2:
        # No args — transcribe all audiobooks that don't have text
        audio_files = sorted(AUDIO_DIR.glob("*.m4b"))
        for af in audio_files:
            stem = af.stem.replace(" ", "_").replace("-", "_")
            text_path = TEXT_DIR / f"{stem}.json"
            if text_path.exists():
                print(f"SKIP (already exists): {af.name}", flush=True)
                continue
            try:
                transcribe_book(str(af))
            except Exception as e:
                print(f"ERROR on {af.name}: {e}", flush=True)
                continue
    else:
        # Transcribe specific file
        audio_path = sys.argv[1]
        if not os.path.exists(audio_path):
            # Try as a name in the audio dir
            audio_path = str(AUDIO_DIR / audio_path)
        transcribe_book(audio_path)


if __name__ == "__main__":
    main()
