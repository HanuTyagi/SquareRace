"""renderer.py — Drawing engine for the Square Race.

Handles:
  - Pre-baking the static map surface (walls, floor, checkered zones)
  - Drawing racer trails with fading alpha + shrinking size
  - Drawing racers (normal, armed, terminator states)
  - Drawing HUD text (winner announcement, timer)

Note on headless environments / pygame font:
- Some environments (or unsupported Python/pygame builds) may not provide pygame.font.
- We treat HUD as optional and will gracefully skip text rendering if fonts are unavailable.

Important: pygame implements module access via __getattr__ and may raise NotImplementedError
when a submodule (e.g. font) is missing. We must catch BaseException classes broadly here.
"""

import math

import pygame

from config import (
    WIDTH,
    HEIGHT,
    TILE_SIZE,
    GRID_W,
    GRID_H,
    SQUARE_SIZE,
    TRAIL_LENGTH,
    TRAIL_ALPHA_MAX,
    TRAIL_MIN_SCALE,
    COLOR_WALL,
    COLOR_PATH,
    COLOR_CHECKER_1,
    COLOR_CHECKER_2,
    COLOR_FINISH_1,
    COLOR_FINISH_2,
    COLOR_KNIFE,
    COLOR_GUN_ITEM,
    COLOR_HUD_TEXT,
    COLOR_SHRINK,
    COLOR_BLOCKER,
)
from map_generator import TILE_WALL, TILE_FINISH


def _draw_checkered(surface, rect, c1, c2, checks=2):
    """Draw a checkered pattern inside the given rect."""

    cw = rect.width // checks
    ch = rect.height // checks
    for row in range(checks):
        for col in range(checks):
            color = c1 if (row + col) % 2 == 0 else c2
            pygame.draw.rect(
                surface,
                color,
                pygame.Rect(rect.x + col * cw, rect.y + row * ch, cw, ch),
            )


def bake_map_surface(grid):
    """Pre-render the entire static map to a single Surface."""

    surf = pygame.Surface((WIDTH, HEIGHT))
    surf.fill(COLOR_PATH)
    for y in range(GRID_H):
        for x in range(GRID_W):
            tile = grid[y][x]
            rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
            if tile == TILE_WALL:
                pygame.draw.rect(surf, COLOR_WALL, rect)
            elif tile == TILE_FINISH:
                _draw_checkered(surf, rect, COLOR_FINISH_1, COLOR_FINISH_2, 3)
    return surf


def draw_items(surface, item_spawns):
    """Draw typed item tiles (knife / gun) from dynamic spawn map."""

    for (x, y), item_type in item_spawns.items():
        rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
        if item_type == "gun":
            _draw_checkered(surface, rect, COLOR_GUN_ITEM, COLOR_CHECKER_2, 2)
        elif item_type == "knife":
            _draw_checkered(surface, rect, COLOR_CHECKER_1, COLOR_CHECKER_2, 2)


def draw_active_blockers(surface, blocker_tiles):
    """Draw currently closed moving blockers."""

    for x, y in blocker_tiles:
        pygame.draw.rect(
            surface,
            COLOR_BLOCKER,
            pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE),
        )


def draw_trails(surface, racers):
    """Draw fading, shrinking trails for each active racer."""

    for racer in racers:
        if not racer["alive"]:
            continue
        color = racer["draw_color"]
        hist = racer["history"]
        n = max(1, len(hist))
        for i, (hx, hy) in enumerate(hist):
            frac = i / n
            alpha = int(TRAIL_ALPHA_MAX * frac)
            t_size = SQUARE_SIZE * (TRAIL_MIN_SCALE + (1.0 - TRAIL_MIN_SCALE) * frac)
            offset = t_size / 2
            pygame.draw.rect(
                surface,
                (*color, alpha),
                pygame.Rect(hx - offset, hy - offset, t_size, t_size),
            )


def draw_racers(surface, racers):
    """Draw each alive racer square and weapon indicators."""

    for racer in racers:
        if not racer["alive"]:
            continue
        px, py = racer["body"].position
        half = SQUARE_SIZE // 2

        # Main square
        pygame.draw.rect(
            surface,
            racer["draw_color"],
            (int(px - half), int(py - half), SQUARE_SIZE, SQUARE_SIZE),
        )

        # Knife indicator: small triangle on the leading edge
        if racer.get("held_item") == "knife":
            vx, vy = racer["body"].velocity
            if vx != 0 or vy != 0:
                angle = math.atan2(vy, vx)
            else:
                angle = 0
            tip_x = px + math.cos(angle) * (half + 6)
            tip_y = py + math.sin(angle) * (half + 6)
            perp = angle + math.pi / 2
            base1 = (px + math.cos(perp) * 4, py + math.sin(perp) * 4)
            base2 = (px - math.cos(perp) * 4, py - math.sin(perp) * 4)
            pygame.draw.polygon(
                surface,
                COLOR_KNIFE,
                [(int(tip_x), int(tip_y)), (int(base1[0]), int(base1[1])), (int(base2[0]), int(base2[1]))],
            )


def draw_shrink_tiles(overlay_surface, tiles):
    """Draw newly shrunk tiles onto persistent shrink overlay."""

    for x, y in tiles:
        pygame.draw.rect(
            overlay_surface,
            COLOR_SHRINK,
            pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE),
        )


# Lazy font cache (avoid re-creating every frame)
_font_cache = {}
_fonts_available = None


def _ensure_fonts():
    """Return True if pygame.font is available and initialized."""

    global _fonts_available
    if _fonts_available is not None:
        return _fonts_available

    try:
        # pygame uses __getattr__ which may raise NotImplementedError when submodules are missing.
        pygame_font = pygame.font  # may raise
        pygame_font.init()  # may raise
        _fonts_available = True
    except BaseException:
        _fonts_available = False

    return _fonts_available


def _get_font(size):
    """Get or create a cached pygame font of the given size."""

    if not _ensure_fonts():
        return None

    if size not in _font_cache:
        try:
            _font_cache[size] = pygame.font.SysFont(None, size)
        except BaseException:
            try:
                _font_cache[size] = pygame.font.Font(None, size)
            except BaseException:
                _font_cache[size] = None
    return _font_cache[size]


def draw_hud(surface, winner_name=None, elapsed_sec=0.0):
    """Draw winner announcement or timer text.

    If pygame font is unavailable, this function becomes a no-op.
    """

    font = _get_font(40)
    if font is None:
        return

    if winner_name:
        text = font.render(f"{winner_name} Wins!", True, COLOR_HUD_TEXT)
        rect = text.get_rect(center=(WIDTH // 2, HEIGHT // 2))
        backing = rect.inflate(20, 10)
        s = pygame.Surface(backing.size, pygame.SRCALPHA)
        s.fill((0, 0, 0, 200))
        surface.blit(s, backing.topleft)
        surface.blit(text, rect)
    else:
        timer_font = _get_font(24)
        if timer_font is None:
            return
        timer_text = timer_font.render(f"{elapsed_sec:.1f}s", True, (180, 180, 180))
        surface.blit(timer_text, (WIDTH - 60, 8))
