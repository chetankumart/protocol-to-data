#!/usr/bin/env python3
"""Record a narrated browser demo of protocol-to-data (Playwright + macOS TTS + ffmpeg).

Self-contained, reusable, and OUTSIDE the frozen `src/` tree — it only drives the running
web UI, it never imports or touches the core package.

Four phases (see .claude/skills/record-demo/SKILL.md):
  1. Pre-generate one narration clip per step with macOS `say`.
  2. Record the browser with Playwright, playing each clip and WAITING for it before acting
     (audio + on-screen action stay in sync), tracking each clip's wall-clock offset.
  3. (App-specific login — protocol-to-data has none, so this is a no-op here.)
  4. Merge with ffmpeg: re-encode video to H.264 and mix each clip back in at its offset.
     Steps flagged with a `speed` > 1 are time-compressed (setpts) so a long live extraction
     is fast-forwarded in the FINAL MP4 — zero manual editing required.

Fixes baked in (all verified): device_scale_factor=1 (no Retina crop) · libx264 re-encode
(WebM/VP8 won't play in .mp4) · per-step adelay mixing (audio lines up with its action) ·
defensive actions (a changed selector degrades to "narrate over it", never crashes).

Usage:
  python scripts/record_demo.py                         # deterministic nav+narration demo (no API key)
  python scripts/record_demo.py --live-run              # full demo: upload a real protocol, run the
                                                        # loop, walk the data, API page, Copilot chart
  python scripts/record_demo.py --live-run --protocol data/protocols/Prot_000-amgen.pdf
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

DEFAULT_URL = "http://localhost:7860"                       # local app for the full-power run
DEFAULT_LIVE_URL = "https://protocol-to-data.onrender.com/"  # deployment proof
DEFAULT_PROTOCOL = "data/protocols/Prot_000-amgen.pdf"      # 179-page oncology (strongest story)
DEFAULT_VOICE = "Samantha"          # macOS voices: Samantha, Reed, Daniel, Karen, Moira
DEFAULT_RATE = 175                  # words per minute
DEFAULT_OUTPUT = "protocol_to_data_demo.mp4"
VIEWPORT = {"width": 1440, "height": 900}
LOOP_SPEEDUP = 8.0                  # fast-forward factor for the live extraction segment
LOOP_WAIT_S = 420                   # max seconds to wait for the full loop (extract→repair→anomalies)


# --------------------------------------------------------------------------- demo script

def build_demo_script(url: str, *, live_run: bool, live_url: str, protocol: str) -> list[dict]:
    """Return the ordered demo steps.

    Each step: {narration, action, detail, pause_after, speed?}. Abbreviations are spaced so
    TTS spells them out ("S D T M", not "sdtm"). `speed` > 1 time-compresses that step's video
    segment in the final MP4. The default (no --live-run) script is deterministic and needs no
    API key; --live-run drives the real pipeline end to end.
    """
    if not live_run:
        return [
            {"narration": "Welcome to protocol to data. It turns a clinical trial protocol into a "
                          "validated, synthetic S D T M dataset in one agentic loop, driven by Claude.",
             "action": "navigate", "detail": url, "pause_after": 2.0},
            {"narration": "This is the Pipeline tab. Drop in a protocol P D F, pick a subject count "
                          "and a seed for reproducibility, then run the loop.",
             "action": "none", "detail": None, "pause_after": 2.0},
            {"narration": "Claude extracts a typed study design, generates the data, validates it, "
                          "and repairs its own failures — a bounded agent, not a pipeline.",
             "action": "none", "detail": None, "pause_after": 2.0},
            {"narration": "Now let's switch to the Data Copilot.",
             "action": "click_tab", "detail": "💬 Data Copilot", "pause_after": 2.5},
            {"narration": "Ask questions about the generated data in plain English, and it renders "
                          "interactive charts, memory-safely with Duck D B.",
             "action": "none", "detail": None, "pause_after": 2.5},
            {"narration": "From a protocol P D F to analyzable, reproducible clinical data. "
                          "Built with Claude. Thanks for watching.",
             "action": "none", "detail": None, "pause_after": 2.5},
        ]

    # ---- full live demo ----
    return [
        {"narration": "This is protocol to data, live and deployed on Render. It turns a clinical "
                      "trial protocol into a validated, synthetic S D T M dataset, driven by Claude.",
         "action": "navigate", "detail": live_url, "pause_after": 3.0},
        {"narration": "Here's the same app running locally for a full-power run on a real, "
                      "one-hundred-and-seventy-nine-page oncology protocol.",
         "action": "navigate", "detail": url, "pause_after": 2.0},
        {"narration": "Let's upload the protocol P D F straight from disk.",
         "action": "upload", "detail": protocol, "pause_after": 2.0},
        {"narration": "Forty subjects, a fixed seed for reproducibility, five injected anomalies — "
                      "and run the loop.",
         "action": "click", "detail": "#main_run_btn", "pause_after": 1.5},
        {"narration": "Watch the live agent narration. Claude extracts the design, generates the "
                      "data, validation catches oncology domains the generator can't build, and "
                      "Claude repairs its own design and re-validates — clean. Then it injects five "
                      "data-quality defects and a second Claude agent catches all five.",
         "action": "wait_for_loop", "detail": None, "pause_after": 2.0, "speed": LOOP_SPEEDUP},
        {"narration": "The generated data files are ready. Here are the labs — you can see the "
                      "docetaxel arm's neutrophil counts falling, real myelosuppression.",
         "action": "select_domain", "detail": "LB", "pause_after": 3.0},
        {"narration": "And adverse events, each verbatim term coded to its Med D R A preferred term.",
         "action": "select_domain", "detail": "AE", "pause_after": 3.0},
        {"narration": "Now the Data Copilot — chat with the generated data.",
         "action": "click_tab", "detail": "💬 Data Copilot", "pause_after": 1.5},
        # Copilot MUST run before the API beat: `use_api` does go_back(), which reloads the app
        # and clears the session output-dir — after it, the Copilot has no data.
        # Use the exact SDTM code (NEUT) — the Copilot schema doesn't expose distinct values, so
        # "neutrophil" alone makes the model guess a wrong code (e.g. ANC) and match nothing.
        {"narration": "One plain-English question — bar chart of average N E U T, the neutrophil "
                      "count, per arm. It writes a Duck D B query, runs it on the data, and plots "
                      "the answer: the docetaxel arm sits well below sotorasib — real "
                      "myelosuppression. Biologically responsive, not random.",
         "action": "type_chat", "detail": "bar chart of average NEUT per arm",
         "pause_after": 8.0},
        {"narration": "And everything here is API-first. The Use via A P I page gives drop-in code "
                      "to generate a dataset programmatically.",
         "action": "use_api", "detail": None, "pause_after": 4.0},
        {"narration": "From a protocol P D F to analyzable, reproducible clinical data — deployed, "
                      "API-first, built with Claude. Thanks for watching.",
         "action": "none", "detail": None, "pause_after": 2.5},
    ]


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
            page.goto(detail, wait_until="load", timeout=90_000)
            # Wait for the app to actually render (the H1) — matters for a cold onrender wake,
            # otherwise the beat films a blank white page.
            try:
                page.get_by_text("protocol-to-data", exact=False).first.wait_for(timeout=60_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(2000)
        elif action == "click":
            page.click(detail, timeout=8_000)
        elif action == "click_tab":
            try:
                page.get_by_role("tab", name=detail).click(timeout=6_000)
            except PWTimeout:
                page.get_by_text(detail, exact=False).first.click(timeout=6_000)
        elif action == "upload":
            # Uncheck the bundled sample so the uploaded file is actually used
            # (precedence is sample → URL → file — leaving it checked ignores the upload).
            try:
                page.get_by_label("Use bundled CARDIO-HF sample").uncheck(timeout=6_000)
            except Exception:  # noqa: BLE001
                try:
                    page.get_by_text("Use bundled CARDIO-HF sample", exact=False).first.click(timeout=4_000)
                except Exception:  # noqa: BLE001
                    log("      ⚠️  could not uncheck the sample box — upload may be ignored")
            # Two file inputs exist (protocol uploader + Copilot attachment); the protocol one is
            # first in DOM (Pipeline tab renders before Copilot). .first avoids a strict-mode error.
            page.locator("input[type=file]").first.set_input_files(detail, timeout=15_000)
            page.wait_for_timeout(1500)
        elif action == "select_domain":
            # Open the "Domain" dropdown and pick an option (data shows in the Pipeline tab).
            try:
                page.get_by_label("Domain").click(timeout=6_000)
            except Exception:  # noqa: BLE001
                page.get_by_text("Domain", exact=True).first.click(timeout=4_000)
            try:
                page.get_by_role("option", name=detail, exact=False).first.click(timeout=5_000)
            except Exception:  # noqa: BLE001
                page.get_by_text(detail, exact=True).first.click(timeout=4_000)
        elif action == "use_api":
            # Gradio's footer "Use via API" link opens a separate API view; show it, then return.
            try:
                page.get_by_role("link", name="Use via API").click(timeout=6_000)
            except PWTimeout:
                page.get_by_text("Use via API", exact=False).first.click(timeout=6_000)
            page.wait_for_timeout(3500)
            try:
                page.go_back()
            except Exception:  # noqa: BLE001
                pass
        elif action == "type_chat":
            box = page.get_by_role("textbox").last
            box.click(timeout=6_000)
            box.fill(detail)
            box.press("Enter")
        elif action == "wait_for_loop":
            # The run streams "PASS" mid-flight, THEN injects/detects anomalies; the Domain
            # dropdown only gets a value on the final yield. Poll it so we release when the run
            # is truly done (data on disk) — otherwise the data/Copilot beats find nothing.
            deadline = time.monotonic() + LOOP_WAIT_S
            ready = False
            while time.monotonic() < deadline:
                try:
                    if page.get_by_label("Domain").input_value(timeout=2_000):
                        ready = True
                        break
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(2_000)
            if not ready:
                log("      ⚠️  loop did not finish (Domain dropdown empty) in time — continuing")
        else:
            log(f"      ⚠️  unknown action '{action}' — skipped")
    except Exception as e:  # noqa: BLE001 — never let one action kill the recording
        log(f"      ⚠️  action '{action}' ({detail}) failed: {type(e).__name__}: {e}")


def record(steps: list[dict], url: str, tmp: Path, *, headless: bool, mute: bool) -> Path:
    """Phase 2 — record the browser, play each clip, WAIT, then act. Returns the raw WebM path."""
    from playwright.sync_api import sync_playwright
    print(f"🎥  Phase 2: recording (headless={headless})…")
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
            step["offset"] = time.monotonic() - start
            tag = f"  ({step['speed']:.0f}x)" if step.get("speed", 1.0) != 1.0 else ""
            log(f"    [{i+1}/{len(steps)}] +{step['offset']:6.1f}s{tag}  {step['narration'][:52]}…")
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


def _run_ffmpeg(cmd: list[str]) -> None:
    """Run ffmpeg, surfacing the tail of stderr on failure (which we otherwise swallow)."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write("ffmpeg failed:\n" + "\n".join(res.stderr.splitlines()[-15:]) + "\n")
        raise RuntimeError("ffmpeg merge failed")


def _audio_filters(steps: list[dict], offsets_ms: list[int], total: float) -> tuple[list[str], list[str]]:
    """Silence-base + one delayed, level-preserving clip per step. Returns (filter_parts, inputs)."""
    parts = [f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={total:.3f}[base]"]
    inputs: list[str] = []
    labels = ["[base]"]
    for i, step in enumerate(steps):
        inputs += ["-i", str(step["audio"])]
        idx = i + 1                                 # input 0 is the video
        parts.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,"
                     f"adelay={offsets_ms[i]}|{offsets_ms[i]}[a{i}]")
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[aout]")
    return parts, inputs


def merge(steps: list[dict], raw_video: Path, output: Path) -> float:
    """Phase 4 — re-encode to H.264 and mix clips in. Steps with `speed`>1 are time-compressed."""
    dur = _video_duration(raw_video)
    has_speed = any(abs(s.get("speed", 1.0) - 1.0) > 1e-6 for s in steps)
    print(f"✂️  Phase 4: merging {'(with speed-ramp) ' if has_speed else ''}"
          f"audio + video with ffmpeg…")

    n = len(steps)
    starts = [s["offset"] for s in steps]
    ends = [starts[i + 1] for i in range(n - 1)] + [dur]

    if not has_speed:
        # Simple path (video plays 1x): clips placed at their raw offsets.
        audio_parts, audio_inputs = _audio_filters(steps, [int(s["offset"] * 1000) for s in steps], dur)
        cmd = ["ffmpeg", "-y", "-i", str(raw_video), *audio_inputs,
               "-filter_complex", ";".join(audio_parts),
               "-map", "0:v", "-map", "[aout]",
               "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(output)]
        _run_ffmpeg(cmd)
        final = dur
    else:
        # Speed-ramp path: split the video at step boundaries, time-warp each segment, concat.
        speeds = [max(s.get("speed", 1.0), 0.01) for s in steps]
        new_durs = [max(ends[i] - starts[i], 0.0) / speeds[i] for i in range(n)]
        new_starts, acc = [], 0.0
        for d in new_durs:
            new_starts.append(acc)
            acc += d
        total = acc

        vparts = ["[0:v]split=" + str(n) + "".join(f"[c{i}]" for i in range(n))]
        vlabels = []
        for i in range(n):
            end_expr = f":end={ends[i]:.3f}" if i < n - 1 else ""     # last segment runs to EOF
            vparts.append(f"[c{i}]trim=start={starts[i]:.3f}{end_expr},"
                          f"setpts=(PTS-STARTPTS)/{speeds[i]:.4f}[v{i}]")
            vlabels.append(f"[v{i}]")
        vparts.append("".join(vlabels) + f"concat=n={n}:v=1:a=0[vout]")

        audio_parts, audio_inputs = _audio_filters(steps, [int(s * 1000) for s in new_starts], total)
        cmd = ["ffmpeg", "-y", "-i", str(raw_video), *audio_inputs,
               "-filter_complex", ";".join(vparts + audio_parts),
               "-map", "[vout]", "-map", "[aout]",
               "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(output)]
        _run_ffmpeg(cmd)
        final = total

    size = output.stat().st_size / 1e6
    print(f"✅  Done: {output}  ({final:.0f}s, {size:.1f} MB)")
    return final


# --------------------------------------------------------------------------------- main

def _prewarm(url: str) -> None:
    """Poll a cold free-tier instance until it's truly awake (HTTP 200), so its in-video load is
    fast. curl uses system certs — Python's urllib trips on macOS SSL roots."""
    print(f"🔥  Pre-warming {url} …")
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "--max-time", "45", url], capture_output=True, text=True)
        if r.stdout.strip() == "200":
            print("    → awake (200)")
            return
        time.sleep(3)
    print("    → warm-up incomplete — continuing (beat may show a cold page)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Record a narrated protocol-to-data demo video.")
    ap.add_argument("--url", default=DEFAULT_URL, help="local app URL for the full-power run")
    ap.add_argument("--live-url", default=DEFAULT_LIVE_URL, help="deployed URL shown as proof")
    ap.add_argument("--protocol", default=DEFAULT_PROTOCOL, help="protocol PDF to upload (--live-run)")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", type=int, default=DEFAULT_RATE)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--live-run", action="store_true",
                    help="upload a real protocol, run the loop, walk data, API + Copilot "
                         "(needs the app up + ANTHROPIC_API_KEY)")
    ap.add_argument("--headless", action="store_true", help="no visible window (CI/test)")
    ap.add_argument("--mute", action="store_true", help="pace without speaker output (CI/test)")
    ap.add_argument("--keep-temp", action="store_true", help="don't delete the temp working dir")
    args = ap.parse_args()

    check_prereqs()
    if args.live_run and not Path(args.protocol).exists():
        print(f"❌ Protocol not found: {args.protocol}")
        sys.exit(1)

    steps = build_demo_script(args.url, live_run=args.live_run,
                              live_url=args.live_url, protocol=str(Path(args.protocol).resolve()))
    tmp = Path(tempfile.mkdtemp(prefix="ptd_demo_"))
    print(f"📁  Working dir: {tmp}")
    try:
        if args.live_run:
            _prewarm(args.live_url)
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
