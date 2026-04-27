#!/usr/bin/env python3
"""
main.py — CLI entry point for the Square Race Video Generator.

Usage:
    python main.py                   # Generate 1 video
    python main.py --count 5         # Generate 5 videos
    python main.py --output ./out    # Custom output directory
"""

import argparse
import os
import sys
import time

from video_pipeline import generate_race_video, init_pipeline, shutdown_pipeline
from config import VIDEO_EXT


def main():
    parser = argparse.ArgumentParser(
        description="Automated Square Race Video Generator",
    )
    parser.add_argument(
        "--count", "-n",
        type=int, default=1,
        help="Number of race videos to generate (default: 1)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str, default="./output",
        help="Output directory for .mp4 files (default: ./output)",
    )
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    print(f"╔══════════════════════════════════════════╗")
    print(f"║   Square Race Video Generator            ║")
    print(f"║   Generating {args.count} video(s)...               ║")
    print(f"╚══════════════════════════════════════════╝")
    print()

    # Initialize pygame once for the entire batch
    screen = init_pipeline()

    success = 0
    failed = 0

    for i in range(1, args.count + 1):
        filename = f"race_{i:03d}{VIDEO_EXT}"
        filepath = os.path.join(args.output, filename)
        print(f"[{i}/{args.count}] Generating {filename}...")
        t0 = time.time()

        if generate_race_video(screen, filepath):
            elapsed = time.time() - t0
            print(f"  Done in {elapsed:.1f}s\n")
            success += 1
        else:
            print(f"  FAILED\n")
            failed += 1

    # Cleanup
    shutdown_pipeline()

    print(f"═══════════════════════════════════════════")
    print(f"  Results: {success} succeeded, {failed} failed")
    print(f"  Output directory: {os.path.abspath(args.output)}")
    print(f"═══════════════════════════════════════════")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
