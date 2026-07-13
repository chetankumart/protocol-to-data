---
name: record-demo
description: Record a narrated browser demo video with Playwright + macOS TTS + ffmpeg
argument-hint: <url> [--voice "Voice Name"] [--output path.mp4] [--live-run]
allowed-tools: [Read, Write, Bash, Glob, Grep, Edit, Agent]
---

# Record Narrated Browser Demo

You are a demo-video recorder. You use **Playwright** to automate a browser session, **macOS
TTS** (`say`) for voice narration, and **ffmpeg** to merge video + audio into a final MP4.

For the `protocol-to-data` project, a ready-made, tested implementation already exists at
`scripts/record_demo.py` — prefer running it (`python scripts/record_demo.py --help`) over
regenerating a script from scratch. Regenerate only for a *different* app or a one-off layout.

## Prerequisites

Verify these are available (check once, fail fast). If any is missing, tell the user exactly
what to install and stop:

- **python3 + Playwright** — `pip install playwright && playwright install chromium`
- **ffmpeg** — `brew install ffmpeg`
- **macOS** — for the `say` TTS and `afplay` commands

## Inputs

Parse the user's arguments:

- **URL** (required): the web app to demo (e.g. `http://localhost:7860` for protocol-to-data).
- **--voice** (optional, default `Samantha`): macOS voice. Options: Samantha, Reed, Daniel, Karen, Moira.
- **--output** (optional, default `demo.mp4`): output file path.
- **--live-run** (optional): drive the real pipeline (needs the app up + any API key it uses),
  rather than the deterministic navigation-only demo.

If only a URL is given, ask: (1) what should the demo walk through? (2) narration text, or
generate it? (3) preferred voice?

## Demo script design

Build a `DEMO_SCRIPT` — an ordered list of steps, each:

```python
{"narration": "Text to speak before acting",
 "action": None | "navigate" | "click" | "click_tab" | "type_chat" | "wait_for_loop",
 "detail": None | "url / selector / tab label / text",
 "pause_after": 3.0}   # seconds to pause after the action, so viewers can read the result
```

Narration guidelines:
- Spell abbreviations letter-by-letter: "S D T M" not "SDTM", "K P I" not "KPI".
- First step = welcome/overview with no action; last step = summary/thank-you with no action.
- **Narrate BEFORE acting** — the viewer hears what's about to happen, then sees it.
- Keep each clip under ~30s (~75 words at 175 wpm); add 3–5s pauses after actions.

## Recording strategy — the script MUST follow this architecture

**Phase 1 — pre-generate audio.** One AIFF per step via
`say -v <voice> -r <rate> -o <path> <text>`. Get each clip's duration from `afinfo`
(no ffmpeg needed for pacing).

**Phase 2 — record browser, play audio live.**
```python
context = browser.new_context(
    viewport={"width": 1440, "height": 900},
    device_scale_factor=1,               # CRITICAL: prevents Retina top-left crop
    record_video_dir=video_dir,
    record_video_size={"width": 1440, "height": 900},   # must match viewport
)
```
Capture `start = time.monotonic()` right after `new_page()` (video timeline t≈0). For each
step: record its `offset = monotonic()-start`, **play the clip with `afplay` and WAIT** for it
to finish, then execute the action, then pause `pause_after`. Never play audio in the
background while acting — that causes drift. Every action must be defensive (try/except) so a
changed selector degrades to "narrate over it", never crashes the run.

**Phase 3 — app-specific login (if any).** Detect a login/connect dialog with
`page.wait_for_selector`, fill credentials from **environment variables (NEVER hardcode)**,
click connect, run a warm-up action. (protocol-to-data has no login — skip.)

**Phase 4 — merge with ffmpeg.** Re-encode the WebM to H.264 (do **not** `-c:v copy` — VP8 in
an MP4 container won't play), and mix each clip back in at its recorded offset:
```
anullsrc=...:atrim=duration=<video_dur>[base];
[i:a]aresample=44100,aformat=channel_layouts=stereo,adelay=<off>|<off>[ai];   # per clip
[base][a0][a1]...amix=inputs=N+1:normalize=0:dropout_transition=0[aout]
```
`-map 0:v -map [aout] -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p -c:a aac -b:a 192k
-movflags +faststart -shortest`.

## Important notes

- **Retina displays**: ALWAYS `device_scale_factor=1`. Without it, Playwright on a DPR=2 Mac
  captures only the top-left quadrant, cropping the right side.
- **Audio sync**: play narration FIRST, wait for it, THEN act. Background audio drifts.
- **Codec**: re-encode video to libx264 + `-pix_fmt yuv420p` for universal playback.
- **Credentials**: `os.environ.get("VAR")` — never hardcode passwords.
- **Temp files**: `tempfile.mkdtemp()`; clean up on exit (or `--keep-temp` to inspect).
- **Headless**: default `headless=False` so the user can watch; allow `--headless` for CI.
- **Outputs**: print final file path, duration, and size when done.

## Execution

1. Write the complete Python script to a temp file (or reuse `scripts/record_demo.py`).
2. Run it with `PYTHONUNBUFFERED=1 python3 -u <script>`.
3. Report results: file path, duration, size.
