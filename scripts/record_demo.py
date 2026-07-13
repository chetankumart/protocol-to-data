#!/usr/bin/env python3
"""Record a narrated browser demo of protocol-to-data (Playwright + macOS TTS + ffmpeg).

Self-contained, reusable, and OUTSIDE the frozen `src/` tree — it only drives the running
web UI, it never imports or touches the core package.

Four phases (see .claude/skills/record-demo/SKILL.md):
  1. Pre-generate one narration clip per step with macOS `say`.
  2. Record the browser with Playwright, playing each clip and WAITING for it before acting
     (so audio and on-screen action stay in sync), tracking each clip's wall-clock offset.
  3. (App-specific login — protocol-to-data has none, so this is a no-op here.)
  4. Merge with ffmpeg: re-encode video to H.264 and mix each clip back in at its exact
     recorded offset over a silence base track.

Fixes over a naive recorder (all verified below):
  • device_scale_factor=1  → no Retina top-left crop.
  • re-encode to libx264   → Playwright's WebM/VP8 actually plays inside an .mp4.
  • per-step adelay mixing  → audio lines up with the action it narrates (no blind overlay).
  • every action is defensive → a changed selector degrades to "narrate over it", never a crash.

Usage:
  python scripts/record_demo.py                         # deterministic nav+narration demo
  python scripts/record_demo.py --live-run              # also click Run and wait for the loop
  python scripts/record_demo.py --url http://localhost:7860 --voice Samantha --output demo.mp4
  python scripts/record_demo.py --headless --mute       # CI/test: no window, no speaker audio
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_URL = "http://localhost:7860"
DEFAULT_VOICE = "Samantha"          # macOS voices: Samantha, Reed, Daniel, Karen, Moira
DEFAULT_RATE = 175                  # words per minute
DEFAULT_OUTPUT = "protocol_to_data_demo.mp4"
VIEWPORT = {"width": 1440, "height": 900}


# --------------------------------------------------------------------------- demo script

def build_demo_script(url: str, *, live_run: bool) -> list[dict]:
    """Return the ordered list of demo steps.

    Each step: {narration, action, detail, pause_after}. Abbreviations are spaced so TTS
    spells them out ("S D T M", not "sdtm"). The default script is deterministic and needs
    no API key; --live-run inserts the real pipeline run + a Copilot query.
    """
    steps: list[dict] = [
        {"narration": "Welcome to protocol to data. It turns a clinical trial protocol into a "
                      "validated, synthetic S D T M dataset in one agentic loop, driven by Claude.",
         "action": "navigate", "detail": url, "pause_after": 2.0},
        {"narration": "This is the Pipeline tab. You drop in a protocol P D F, pick a subject "
                      "count and a random seed for reproducibility, then run the loop.",
         "action": "none", "detail": None, "pause_after": 2.0},
        {"narration": "Under the hood, Claude reads the prose into a typed study design, "
                      "generates the data, validates it against clinical rules, and repairs its "
                      "own failures. It is a bounded agent, not a pipeline.",
         "action": "none", "detail": None, "pause_after": 2.0},
    ]

    if live_run:
        steps += [
            {"narration": "Let's run it live on the bundled cardiology sample.",
             "action": "click", "detail": "#main_run_btn", "pause_after": 1.0},
            {"narration": "Claude is extracting the design, generating the data, and validating "
                          "it now. Watch the loop narrate itself in real time.",
             "action": "wait_for_loop", "detail": None, "pause_after": 2.0},
        ]

    steps += [
        {"narration": "Now let's switch to the Data Copilot.",
         "action": "click_tab", "detail": "💬 Data Copilot", "pause_after": 2.5},
    ]

    if live_run:
        steps.append(
            {"narration": "Ask a question in plain English, and it writes a Duck D B query and "
                          "renders an interactive chart, memory-safely.",
             "action": "type_chat", "detail": "bar chart of subjects per arm", "pause_after": 5.0})
    else:
        steps.append(
            {"narration": "Here you ask questions about the generated data in plain English, and "
                          "it renders interactive charts, memory-safely with Duck D B.",
             "action": "none", "detail": None, "pause_after": 2.5})

    steps.append(
        {"narration": "From a protocol P D F to analyzable, reproducible clinical data. "
                      "Built with Claude. Thanks for watching.",
         "action": "none", "detail": None, "pause_after": 2.5})
    return steps


# --------------------------------------------------------------------------- prerequisites

def check_prereqs() -> None:
    """Fail fast with an actionable message if a required tool is missing."""
    missing = []
    if sys.platform != "darwin":
        missing.append("macOS (this recorder uses the `say` and `afplay` commands)")
    if shutil.which("say") is None:
        missing.append("`say` (macOS text-to-speech)")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg — install with: brew install ffmpeg")
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright — install with: pip install playwright && playwright install chromium")
    if missing:
        print("❌ Missing prerequisites:")
        for m in missing:
            print(f"   • {m}")
        sys.exit(1)


# ------------------------------------------------------------------- phase 1: synth audio

def _audio_duration(path: Path) -> float:
    """Seconds of an AIFF clip via macOS `afinfo` (no ffmpeg dependency for pacing)."""
    try:
        out = subprocess.run(["afinfo", str(path)], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if "estimated duration" in line:
                return float(line.split(":")[1].strip().split()[0])
    except Exception:  # noqa: BLE001
        pass
    return 3.0  # safe fallback


def synth_audio(steps: list[dict], voice: str, rate: int, tmp: Path) -> None:
    """Phase 1 — one AIFF per step; annotate each step with its file path + duration."""
    print(f"🎙️  Phase 1: generating {len(steps)} narration clips (voice={voice}, rate={rate})…")
    for i, step in enumerate(steps):
        clip = tmp / f"narration_{i:02d}.aiff"
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(clip), step["narration"]],
                       check=True)
        step["audio"] = clip
        step["duration"] = _audio_duration(clip)
    print(f"    → {len(steps)} clips written to {tmp}")


# ------------------------------------------------------------------- phase 2/3: record

def _do_action(page, action: str, detail, log) -> None:
    """Execute one step's browser action defensively — a failure logs and continues."""
    from playwright.sync_api import TimeoutError as PWTimeout
    try:
        if action in ("none", None):
            return
        if action == "navigate":
            page.goto(detail, wait_until="load", timeout=30_000)
            page.wait_for_timeout(1500)
        elif action == "click":
            page.click(detail, timeout=8_000)
        elif action == "click_tab":
            # Gradio tabs render as role=tab buttons; fall back to any element with the text.
            try:
                page.get_by_role("tab", name=detail).click(timeout=6_000)
            except PWTimeout:
                page.get_by_text(detail, exact=False).first.click(timeout=6_000)
        elif action == "type_chat":
            box = page.get_by_role("textbox").last
            box.click(timeout=6_000)
            box.fill(detail)
            box.press("Enter")
        elif action == "wait_for_loop":
            # Wait for the loop to finish: the narration panel prints a PASS/errors line.
            try:
                page.get_by_text("PASS", exact=False).first.wait_for(timeout=180_000)
            except PWTimeout:
                log("      ⚠️  loop did not report PASS within 180s — continuing")
        else:
            log(f"      ⚠️  unknown action '{action}' — skipped")
    except Exception as e:  # noqa: BLE001 — never let one action kill the recording
        log(f"      ⚠️  action '{action}' ({detail}) failed: {type(e).__name__}: {e}")


def record(steps: list[dict], url: str, tmp: Path, *, headless: bool, mute: bool) -> Path:
    """Phase 2 — record the browser, play each clip, WAIT, then act. Returns the raw WebM path."""
    from playwright.sync_api import sync_playwright
    print(f"🎥  Phase 2: recording {url} (headless={headless})…")
    video_dir = tmp / "video"
    video_dir.mkdir(exist_ok=True)

    def log(msg):
        print(msg)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=1,                  # CRITICAL: no Retina top-left crop
            record_video_dir=str(video_dir),
            record_video_size=VIEWPORT,             # must match viewport
        )
        page = context.new_page()
        start = time.monotonic()                    # video timeline t≈0 starts here
        for i, step in enumerate(steps):
            step["offset"] = time.monotonic() - start   # when this clip plays, vs video start
            log(f"    [{i+1}/{len(steps)}] +{step['offset']:5.1f}s  {step['narration'][:58]}…")
            if mute:
                time.sleep(step["duration"])        # pace only, no speaker output (for CI/tests)
            else:
                subprocess.run(["afplay", str(step["audio"])], check=False)  # blocks = waits
            _do_action(page, step["action"], step["detail"], log)
            page.wait_for_timeout(int(step["pause_after"] * 1000))
        video = page.video
        context.close()                             # flushes the video file
        browser.close()
        raw = Path(video.path())
    print(f"    → raw video: {raw.name} ({raw.stat().st_size/1e6:.1f} MB)")
    return raw


# --------------------------------------------------------------------- phase 4: merge

def _video_duration(path: Path) -> float:
    """Seconds of the recorded video. Prefers ffprobe; falls back to parsing `ffmpeg -i`
    (static ffmpeg builds often ship no ffprobe), so any ffmpeg on PATH works."""
    if shutil.which("ffprobe"):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(path)],
                             capture_output=True, text=True, check=True).stdout.strip()
        try:
            return float(out)
        except ValueError:
            pass
    import re
    res = subprocess.run(["ffmpeg", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
    if m:
        h, mm, ss = m.groups()
        return int(h) * 3600 + int(mm) * 60 + float(ss)
    return 0.0


def merge(steps: list[dict], raw_video: Path, output: Path) -> None:
    """Phase 4 — re-encode video to H.264 and mix each clip in at its recorded offset."""
    print("✂️  Phase 4: merging audio + video with ffmpeg…")
    dur = _video_duration(raw_video)
    inputs = ["-i", str(raw_video)]
    parts = [f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={dur:.3f}[base]"]
    labels = ["[base]"]
    for i, step in enumerate(steps):
        off = int(step["offset"] * 1000)            # ms
        inputs += ["-i", str(step["audio"])]
        idx = i + 1                                 # input 0 is the video
        parts.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,"
                     f"adelay={off}|{off}[a{i}]")
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:"
                 "dropout_transition=0[aout]")
    filter_complex = ";".join(parts)

    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", filter_complex,
           "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-shortest", str(output)]
    subprocess.run(cmd, check=True, capture_output=True)
    size = output.stat().st_size / 1e6
    print(f"✅  Done: {output}  ({dur:.0f}s, {size:.1f} MB)")


# --------------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Record a narrated protocol-to-data demo video.")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", type=int, default=DEFAULT_RATE)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--live-run", action="store_true",
                    help="click Run and wait for the real loop (needs ANTHROPIC_API_KEY + app)")
    ap.add_argument("--headless", action="store_true", help="no visible window (CI/test)")
    ap.add_argument("--mute", action="store_true", help="pace without speaker output (CI/test)")
    ap.add_argument("--keep-temp", action="store_true", help="don't delete the temp working dir")
    args = ap.parse_args()

    check_prereqs()
    steps = build_demo_script(args.url, live_run=args.live_run)
    tmp = Path(tempfile.mkdtemp(prefix="ptd_demo_"))
    print(f"📁  Working dir: {tmp}")
    try:
        synth_audio(steps, args.voice, args.rate, tmp)
        raw = record(steps, args.url, tmp, headless=args.headless, mute=args.mute)
        merge(steps, raw, Path(args.output).resolve())
    finally:
        if args.keep_temp:
            print(f"📁  Temp kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
