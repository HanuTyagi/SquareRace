"""
video_pipeline.py — Module E: Headless rendering & .mp4 encoding.

Handles:
  - Headless pygame initialization (no visible window)
  - Frame capture: pygame surface → numpy array → BGR for OpenCV
  - cv2.VideoWriter management
  - Single-race simulation loop with retry-on-failure
"""

import os
import sys
import numpy as np
import cv2
import pygame

from config import (
    WIDTH, HEIGHT, FPS, VIDEO_CODEC, VIDEO_EXT, MAX_ATTEMPTS,
)
from map_generator import generate_arena
from physics_engine import (
    create_space, add_walls, create_racers,
    enforce_constant_speed, update_trails, step,
)
from renderer import (
    bake_map_surface, draw_trails, draw_racers,
    draw_hud, draw_shrink_tiles,
)
from game_mechanics import GameState


def _init_headless_pygame():
    """Initialize pygame with a hidden display (window exists but is invisible)."""
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.HIDDEN)
    return screen


def _surface_to_bgr(surface):
    """
    Convert a pygame Surface to a (H, W, 3) BGR numpy array
    suitable for cv2.VideoWriter.
    """
    arr = pygame.surfarray.array3d(surface)   # (W, H, 3) RGB
    arr = arr.transpose((1, 0, 2))            # (H, W, 3)
    arr = arr[:, :, ::-1]                     # RGB → BGR
    return np.ascontiguousarray(arr)


def run_single_race(screen):
    """
    Run one complete race simulation.

    Returns
    -------
    result : str
        "win", "timeout", or "all_dead"
    frames : list[np.ndarray]
        BGR frames if result == "win", else empty.
    winner_name : str or None
    """
    # --- Setup ---
    grid, spawn_center, finish_tiles, item_tiles, map_meta = generate_arena()
    space = create_space()
    add_walls(space, grid)
    racers = create_racers(space, spawn_center)
    game = GameState(racers, grid, finish_tiles, item_tiles, map_meta=map_meta)
    map_surface = bake_map_surface(grid)
    trail_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    shrink_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    frames = []
    winner_held_frames = 0       # hold the winner screen for a few seconds
    WINNER_HOLD = int(FPS * 2)   # 2 seconds of winner display

    while True:
        # --- Physics ---
        enforce_constant_speed(racers)
        update_trails(racers)
        step(space)

        # --- Game logic ---
        status = game.update(space)

        # --- Render ---
        screen.blit(map_surface, (0, 0))

        # Trail overlay
        trail_overlay.fill((0, 0, 0, 0))
        draw_trails(trail_overlay, racers)
        screen.blit(trail_overlay, (0, 0))
        if game.newly_shrunk_tiles:
            draw_shrink_tiles(shrink_overlay, game.newly_shrunk_tiles)
        screen.blit(shrink_overlay, (0, 0))

        # Racers
        draw_racers(screen, racers)

        # HUD
        if game.winner:
            draw_hud(screen, winner_name=game.winner)
        else:
            draw_hud(screen, elapsed_sec=game.elapsed_sec)

        # Capture frame
        frames.append(_surface_to_bgr(screen))

        # --- Termination checks ---
        if status == "win":
            winner_held_frames += 1
            if winner_held_frames >= WINNER_HOLD:
                return "win", frames, game.winner

        elif status == "timeout":
            print("  → Timeout! Discarding.")
            return "timeout", [], None

        # All dead check
        alive = [r for r in racers if r["alive"]]
        if len(alive) == 0 and game.winner is None:
            print("  → All racers dead, no winner. Discarding.")
            return "all_dead", [], None


def encode_video(frames, output_path):
    """Write a list of BGR numpy frames to an .mp4 file."""
    if not frames:
        return
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*VIDEO_CODEC)
    writer = cv2.VideoWriter(output_path, fourcc, FPS, (w, h))
    for frame in frames:
        writer.write(frame)
    writer.release()
    print(f"  ✓ Saved: {output_path}  ({len(frames)} frames, {len(frames)/FPS:.1f}s)")


def generate_race_video(screen, output_path, max_attempts=MAX_ATTEMPTS):
    """
    Generate a single race video, retrying up to max_attempts times
    if the simulation results in timeout or total death.

    Parameters
    ----------
    screen : pygame.Surface
        The hidden display surface (created externally so it persists across batches).
    output_path : str
        File path for the output .mp4.
    max_attempts : int
        Retry limit.

    Returns True if a valid video was produced.
    """
    for attempt in range(1, max_attempts + 1):
        print(f"  Attempt {attempt}/{max_attempts}...")
        result, frames, winner = run_single_race(screen)
        if result == "win":
            encode_video(frames, output_path)
            return True
        # else: retry

    print(f"  ✗ Failed to produce a valid race after {max_attempts} attempts.")
    return False


def init_pipeline():
    """Initialize pygame once for the entire batch. Returns screen surface."""
    return _init_headless_pygame()


def shutdown_pipeline():
    """Clean up pygame."""
    from renderer import _font_cache
    _font_cache.clear()
    pygame.quit()
