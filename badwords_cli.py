#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Standalone CLI for BadWords Transcription and Silence Detection
Runs independently of DaVinci Resolve.
"""

import os
import sys
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

def main():
    parser = argparse.ArgumentParser(description="BadWords CLI - Transcribe and analyze audio/video independently.")
    parser.add_argument("--audio", type=str, required=True, help="Path to the input audio or video file.")
    parser.add_argument("--model", type=str, default="medium", help="Whisper model to use (default: medium).")
    parser.add_argument("--lang", type=str, default="auto", help="Language code or 'auto' (default: auto).")
    parser.add_argument("--device", type=str, default="Auto", help="Device to use (Auto, CPU, GPU).")
    parser.add_argument("--fps", type=float, default=24.0, help="Timeline FPS for precise timecode conversion (default: 24.0).")
    
    args = parser.parse_args()

    input_path = os.path.abspath(args.audio)
    if not os.path.exists(input_path):
        print(f"[ERROR] Input file not found: {input_path}")
        sys.exit(1)

    # Output directory relative to the input file
    input_dir = os.path.dirname(input_path)
    output_dir = os.path.join(input_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"==================================================")
    print(f" BADWORDS CLI v12 (Standalone Mode)")
    print(f"==================================================")
    print(f"Input File: {input_path}")
    print(f"Output Dir: {output_dir}")
    print(f"Model: {args.model}, Lang: {args.lang}, Device: {args.device}, FPS: {args.fps}")
    print(f"--------------------------------------------------")

    os_doc = OSDoctor()
    engine = AudioEngine(os_doc, resolve_handler=None)
    
    # Store CLI FPS in the engine for fallback use
    engine._cli_fps = args.fps

    settings = {
        'audio_path': input_path,
        'model': args.model,
        'lang': args.lang,
        'device': args.device,
        'skip_assembly': True,  # Critical to bypass Resolve timeline injection
        'timeline_name': os.path.basename(input_path)
    }

    # Progress Callbacks
    def status_cb(msg):
        print(f"\n[STATUS] {msg}")

    def progress_cb(val):
        if val > 0:
            print(f"[PROGRESS] {val}%")

    start_time = time.time()
    
    # Run the pipeline
    result = engine.run_analysis_pipeline(
        settings, 
        callback_status=status_cb, 
        callback_progress=progress_cb
    )

    if not result:
        print("\n[ERROR] Pipeline failed.")
        sys.exit(1)
        
    words_data, segments_data = result
    
    if not words_data:
        print("\n[ERROR] No words data returned.")
        sys.exit(1)

    # In standalone mode, engine creates the SRT and JSONs in the temp directory.
    # We need to copy them to our desired output directory.
    temp_dir = os_doc.get_temp_folder()
    
    # The engine normally saves test1.json and BW [n] xyz.srt
    # Because we skip assembly, we need to extract the raw generated files.
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    
    final_json_path = os.path.join(output_dir, f"{base_name}_words.json")
    final_srt_path = os.path.join(output_dir, f"{base_name}.srt")
    
    # In engine.py, it generates the current SRT and saves words data.
    # We will write the JSON directly ourselves to be safe.
    import json
    with open(final_json_path, 'w', encoding='utf-8') as f:
        json.dump(words_data, f, ensure_ascii=False, indent=2)
    print(f"\n[SUCCESS] Saved JSON: {final_json_path}")
    
    # Find the generated SRT
    if hasattr(engine, 'current_srt_name') and engine.current_srt_name:
        generated_srt = os.path.join(temp_dir, engine.current_srt_name)
        if os.path.exists(generated_srt):
            shutil.copy2(generated_srt, final_srt_path)
            print(f"[SUCCESS] Saved SRT: {final_srt_path}")
        else:
            print(f"[WARNING] Generated SRT {generated_srt} not found.")
    else:
        print(f"[WARNING] SRT generation was skipped or name missing.")
        
    elapsed = time.time() - start_time
    print(f"--------------------------------------------------")
    print(f" PROCESSING COMPLETE! (Time: {elapsed:.2f}s)")
    print(f"==================================================")

if __name__ == "__main__":
    main()
