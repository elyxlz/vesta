---
name: video-use
description: Use for "edit video", "video editing", "remove filler words", "cut dead space", "color grade", "add subtitles", "burn captions", "B-roll overlay", "launch video", or whenever the user wants footage turned into a polished cut. Wraps browser-use/video-use, a Claude-Code-powered video editor that handles filler removal, auto color grading, 30ms audio fades, burned subtitles, and Manim/Remotion/PIL overlays.
---

# Video-Use - Claude-Code-Powered Video Editor

Wraps [`browser-use/video-use`](https://github.com/browser-use/video-use): a Claude Code agent that edits raw footage into a finished cut. Point it at a directory of clips, tell it what you want, and it:

- Removes filler words ("um", "uh", "like", long dead space) using transcription + precise cuts
- Auto color grades each clip
- Applies 30ms audio fades at every cut so splices don't pop
- Burns subtitles into the final video
- Generates overlays and motion graphics via Manim, Remotion, or PIL
- Self-evaluates the output and iterates until the cut holds up

**Setup**: See [SETUP.md](SETUP.md)

## Usage

```bash
cd <video-dir>
claude "edit these into a launch video"
```

That's it. The nested Claude session reads the clips in the cwd, plans the edit, runs ffmpeg / Manim / Remotion / PIL, and writes the output to the same directory.

### More prompts

```bash
cd ~/Videos/demo-raw
claude "cut filler words, color grade, burn subtitles, 60 seconds max"
claude "assemble a 2-minute product tour from these takes, add lower-thirds for each feature"
claude "take the best 30 seconds for a twitter post, vertical 9:16, punchy subtitles"
```

## Data locations

- **Install root**: `~/Developer/video-use`
- **Env file**: `~/Developer/video-use/.env` (ElevenLabs API key lives here)
- **Working directory**: wherever the source clips are. The nested session runs in that cwd and writes outputs alongside the inputs.

## Requirements

- `ffmpeg` - required, does every cut / encode / fade / burn-in
- `yt-dlp` - optional, lets the nested agent pull clips from URLs
- ElevenLabs API key in `~/Developer/video-use/.env` - required for voice features
- `uv` - used to manage the video-use project's Python deps

## Notes

- **Token cost**: each run spawns a nested Claude Code session that reasons over transcripts, timelines, and per-shot decisions. Long or high-res edits can burn a meaningful amount of tokens. Prefer trimming the input directory to only the clips you want considered before invoking.
- Run from the directory that contains the clips. The nested session uses the cwd as its working set.
- First run on a new machine will download models / deps via `uv sync`; subsequent runs are fast.
- For diagnosing a weird cut, check the nested session's transcript output in the video directory before re-running.
