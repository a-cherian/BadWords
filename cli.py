#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Standalone CLI for BadWords Transcription and Silence Detection
Runs independently of DaVinci Resolve.

Usage:
    python3 badwords_cli.py --audio path/to/audio.wav --lang zh
"""

import os
import sys
import re
import argparse
import shutil
import time

# Ensure we can import from src/
current_dir = os.path.dirname(os.path.realpath(__file__))
src_dir = os.path.join(current_dir, "src")
if src_dir not in sys.path:
    sys.path.append(src_dir)

from osdoc import OSDoctor, log_info, log_error
from engine import AudioEngine


def _find_project_root(start_path: str) -> str:
    """
    Climb up the directory tree from start_path until we find a folder
    whose name starts with a digit and contains ' - '  (e.g. '10 - 仙逆').
    Returns that folder path, or start_path if none is found.
    """
    # Regex: folder name starts with one or more digits followed by ' - '
    _num_prefix = re.compile(r'^\d+\s*-\s+')
    path = os.path.abspath(start_path)
    # Walk up until filesystem root
    while True:
        name = os.path.basename(path)
        if _num_prefix.match(name):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            # Reached filesystem root without finding a project folder
            return start_path
        path = parent


def main():
    parser = argparse.ArgumentParser(
        description="BadWords CLI - Transcribe and analyze audio/video independently of DaVinci Resolve."
    )
    parser.add_argument("--audio",  type=str, required=True,  help="Path to the input audio or video file.")
    parser.add_argument("--model",  type=str, default="medium", help="Whisper model to use (default: medium).")
    parser.add_argument("--lang",   type=str, default="auto",  help="Language code or 'auto' (default: auto).")
    parser.add_argument("--device", type=str, default="Auto",  help="Device to use: Auto, CPU, or GPU (default: Auto).")
    parser.add_argument("--fps",    type=float, default=24.0,  help="Timeline FPS for timecode conversion (default: 24.0).")
    parser.add_argument("--script", type=str, default=None,   help="Optional path to a script/transcript text file for comparison.")

    args = parser.parse_args()

    input_path = os.path.abspath(args.audio)
    if not os.path.exists(input_path):
        print(f"[ERROR] Input file not found: {input_path}")
        sys.exit(1)

    # Climb up from the audio file's folder to find the numbered project root
    audio_dir    = os.path.dirname(input_path)
    project_root = _find_project_root(audio_dir)
    output_dir   = os.path.join(project_root, "output")
    os.makedirs(output_dir, exist_ok=True)

    print(f"==================================================")
    print(f" BADWORDS CLI (Standalone Mode)")
    print(f"==================================================")
    print(f"Input File:   {input_path}")
    print(f"Project Root: {project_root}")
    print(f"Output Dir:   {output_dir}")
    print(f"Model: {args.model} | Lang: {args.lang} | Device: {args.device} | FPS: {args.fps}")
    if args.script:
        print(f"Script:       {args.script}")
    print(f"--------------------------------------------------")

    os_doc = OSDoctor()
    engine = AudioEngine(os_doc, resolve_handler=None)
    engine._cli_fps = args.fps  # Store FPS for headless use

    settings = {
        'audio_path':    input_path,
        'model':         args.model,
        'lang':          args.lang,
        'device':        args.device,
        'skip_assembly': True,          # Bypass DaVinci Resolve timeline injection
        'timeline_name': os.path.basename(input_path),
    }

    if args.script:
        script_path = os.path.abspath(args.script)
        if not os.path.exists(script_path):
            print(f"[ERROR] Script file not found: {script_path}")
            sys.exit(1)
        with open(script_path, 'r', encoding='utf-8') as f:
            settings['script_content'] = f.read()

    # ── Progress Callbacks ─────────────────────────────────────────────────────
    def status_cb(msg):
        print(f"\n[STATUS] {msg}")

    _progress_start = [None]  # mutable cell so the closure can write to it

    def progress_cb(val):
        if val <= 0:
            return
        now = time.time()
        if _progress_start[0] is None:
            _progress_start[0] = now

        elapsed = now - _progress_start[0]
        filled  = int(val / 5)
        bar     = '█' * filled + '░' * (20 - filled)

        # Only show ETA once we have a meaningful sample (>2% done)
        if val >= 2 and elapsed > 0:
            secs_left = int(elapsed / val * (100 - val))
            m, s = divmod(secs_left, 60)
            eta_str = f"ETA ~{m}m {s:02d}s"
        else:
            eta_str = "ETA --:--"

        print(f"\r  [{bar}] {val:3d}%  {eta_str}   ", end='', flush=True)

    start_time = time.time()

    # ── Run the pipeline ───────────────────────────────────────────────────────
    result = engine.run_analysis_pipeline(
        settings,
        callback_status=status_cb,
        callback_progress=progress_cb,
    )

    print()  # newline after progress bar

    if not result:
        print("\n[ERROR] Pipeline failed.")
        sys.exit(1)

    words_data, segments_data = result

    if not words_data:
        print("\n[ERROR] No words data returned.")
        sys.exit(1)

    # ── Save outputs ───────────────────────────────────────────────────────────
    def _safe_path(path: str) -> str:
        """If path exists, return a new path with an incrementing suffix (_1, _2, …)."""
        if not os.path.exists(path):
            return path
        root, ext = os.path.splitext(path)
        n = 1
        while True:
            candidate = f"{root}_{n}{ext}"
            if not os.path.exists(candidate):
                return candidate
            n += 1

    base_name       = os.path.splitext(os.path.basename(input_path))[0]
    final_json_path = _safe_path(os.path.join(output_dir, f"{base_name}_words.json"))
    final_srt_path  = _safe_path(os.path.join(output_dir, f"{base_name}.srt"))

    # Write the JSON directly
    import json
    with open(final_json_path, 'w', encoding='utf-8') as f:
        json.dump(words_data, f, ensure_ascii=False, indent=2)
    print(f"\n[SUCCESS] JSON  → {final_json_path}")

    # Copy the generated SRT from the temp dir
    temp_dir = os_doc.get_temp_folder()
    if hasattr(engine, 'current_srt_name') and engine.current_srt_name:
        generated_srt = os.path.join(temp_dir, engine.current_srt_name)
        if os.path.exists(generated_srt):
            shutil.copy2(generated_srt, final_srt_path)
            print(f"[SUCCESS] SRT   → {final_srt_path}")
        else:
            print(f"[WARNING] Could not find generated SRT at {generated_srt}")
    else:
        print(f"[WARNING] SRT not generated (no current_srt_name).")

    elapsed = time.time() - start_time
    m, s = divmod(int(elapsed), 60)
    print(f"\n--------------------------------------------------")
    print(f" DONE  ({m}m {s:02d}s)")
    print(f"==================================================")


if __name__ == "__main__":
    main()

