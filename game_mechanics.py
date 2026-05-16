"""
game_mechanics.py — Modules C + D: Weapons, Terminator, Death Zone, Win Logic.

Manages:
  - Item tile pickup → random weapon assignment (knife / gun)
  - Knife: melee elimination on racer-vs-racer collision, cooldown drop
  - Gun (Terminator): state change, periodic raycast firing, elimination on hit
  - Death Zone: descending wall that eliminates racers above it
  - Win conditions: finish-line crossing (normal) or last-alive (terminator)
  - Deferred body removal queue (safe mid-step handling)
"""

import random
import math
import pymunk

from config import (
    TILE_SIZE, SQUARE_SIZE, FPS, WIDTH,
    WEAPON_KNIFE_PROB, KNIFE_COOLDOWN_SEC,
    GUN_FIRE_INTERVAL, GUN_RAY_LENGTH,
    COLOR_TERMINATOR,
    MAX_RACE_SECONDS,
)
from physics_engine import CAT_RACER, add_wall_tile
from map_generator import TILE_ITEM, TILE_FLOOR, TILE_WALL, TILE_FINISH, TILE_SHRINK
from shrink_engine import ShrinkEngine


class GameState:
    """
    Mutable game state container, updated each frame by the simulation loop.
    """

    def __init__(self, racers, grid, finish_tiles, item_tiles, map_meta=None):
        self.racers = racers
        self.grid = grid
        self.finish_tiles = set(finish_tiles)
        self.item_tiles = list(item_tiles)        # mutable; items get consumed
        self.pending_removals = []                 # (racer_index,) queued for removal
        self.dropped_knives = []                   # [(grid_x, grid_y, cooldown_remaining)]
        self.winner = None                         # racer name or None
        self.frame_count = 0
        self.elapsed_sec = 0.0
        self.map_meta = map_meta or {}
        self.shrink_engine = ShrinkEngine(self.map_meta)
        self.shrunk_tiles = set()
        self.newly_shrunk_tiles = []

    def _get_grid_coords(self, position):
        px, py = position
        gx, gy = int(px // TILE_SIZE), int(py // TILE_SIZE)
        if not (0 <= gy < len(self.grid) and 0 <= gx < len(self.grid[0])):
            return None
        return gx, gy

    # ──────────────────────────────────────────────
    # Per-frame update — called from the main loop
    # ──────────────────────────────────────────────
    def update(self, space):
        dt = 1.0 / FPS
        self.frame_count += 1
        self.elapsed_sec = self.frame_count / FPS

        self._update_cooldowns(dt)
        self._check_item_pickups()
        self._check_knife_collisions()
        self._fire_guns(space)
        # Legacy directional death-zone pressure is superseded by staged region shrink.
        self._update_shrink(dt, space)
        self._check_finish_line()
        self._check_last_alive()
        self._flush_removals(space)

        # Hard time limit
        if self.elapsed_sec >= MAX_RACE_SECONDS and self.winner is None:
            return "timeout"

        if self.winner is not None:
            return "win"

        return "running"

    def _update_shrink(self, dt, space):
        self.newly_shrunk_tiles = []
        if self.shrink_engine is None:
            return

        new_tiles = self.shrink_engine.update(dt)
        if not new_tiles:
            return

        for x, y in new_tiles:
            if not (0 <= y < len(self.grid) and 0 <= x < len(self.grid[0])):
                continue
            if (x, y) in self.shrunk_tiles:
                continue
            if self.grid[y][x] in (TILE_WALL, TILE_FINISH):
                continue

            self.grid[y][x] = TILE_SHRINK
            self.shrunk_tiles.add((x, y))
            self.newly_shrunk_tiles.append((x, y))
            add_wall_tile(space, x, y)

            # Remove consumed item if shrink covers it.
            if (x, y) in self.item_tiles:
                self.item_tiles.remove((x, y))

        if not self.newly_shrunk_tiles:
            return

        # Simple stable squeeze rule: eliminate racers overlapping any shrunk tile.
        for i, racer in enumerate(self.racers):
            if not racer["alive"]:
                continue
            coords = self._get_grid_coords(racer["body"].position)
            if coords is None:
                continue
            gx, gy = coords
            if (gx, gy) in self.shrunk_tiles:
                self.pending_removals.append(i)

    # ──────────────────────────────────────────────
    # Item pickup
    # ──────────────────────────────────────────────
    def _check_item_pickups(self):
        for racer in self.racers:
            if not racer["alive"] or racer["held_item"] is not None:
                continue
            coords = self._get_grid_coords(racer["body"].position)
            if coords is None:
                continue
            gx, gy = coords
            if (gx, gy) in [(ix, iy) for ix, iy in self.item_tiles]:
                # Assign weapon
                if random.random() < WEAPON_KNIFE_PROB:
                    racer["held_item"] = "knife"
                else:
                    racer["held_item"] = "gun"
                    racer["state"] = "terminator"
                    racer["draw_color"] = COLOR_TERMINATOR
                    racer["gun_timer"] = GUN_FIRE_INTERVAL
                # Consume item
                self.item_tiles.remove((gx, gy))
                self.grid[gy][gx] = TILE_FLOOR

        # Also check dropped knives
        for racer in self.racers:
            if not racer["alive"] or racer["held_item"] is not None:
                continue
            coords = self._get_grid_coords(racer["body"].position)
            if coords is None:
                continue
            gx, gy = coords
            for knife in self.dropped_knives[:]:
                kx, ky, cd = knife
                if cd <= 0 and gx == kx and gy == ky:
                    racer["held_item"] = "knife"
                    self.dropped_knives.remove(knife)

    # ──────────────────────────────────────────────
    # Knife melee
    # ──────────────────────────────────────────────
    def _check_knife_collisions(self):
        alive = [r for r in self.racers if r["alive"]]
        for attacker in alive:
            if attacker["held_item"] != "knife":
                continue
            ax, ay = attacker["body"].position
            for victim in alive:
                if victim is attacker:
                    continue
                vx, vy = victim["body"].position
                dist = math.hypot(ax - vx, ay - vy)
                if dist < SQUARE_SIZE * 1.2:
                    # Eliminate victim
                    idx = self.racers.index(victim)
                    self.pending_removals.append(idx)
                    # Drop knife at collision point
                    drop_gx = int(ax // TILE_SIZE)
                    drop_gy = int(ay // TILE_SIZE)
                    self.dropped_knives.append((drop_gx, drop_gy, KNIFE_COOLDOWN_SEC))
                    attacker["held_item"] = None
                    print(f"  [KNIFE] {attacker['name']} eliminated {victim['name']}!")
                    break  # one kill per frame per attacker

    # ──────────────────────────────────────────────
    # Gun (Terminator) raycast
    # ──────────────────────────────────────────────
    def _fire_guns(self, space):
        dt = 1.0 / FPS
        for racer in self.racers:
            if not racer["alive"] or racer["state"] != "terminator":
                continue
            racer["gun_timer"] -= dt
            if racer["gun_timer"] > 0:
                continue
            racer["gun_timer"] = GUN_FIRE_INTERVAL

            # Raycast along velocity vector
            px, py = racer["body"].position
            vx, vy = racer["body"].velocity
            if vx == 0 and vy == 0:
                continue
            angle = math.atan2(vy, vx)
            end_x = px + math.cos(angle) * GUN_RAY_LENGTH
            end_y = py + math.sin(angle) * GUN_RAY_LENGTH

            # Query all shapes hit by the ray
            hits = space.segment_query(
                (px, py), (end_x, end_y), 1,
                pymunk.ShapeFilter(mask=CAT_RACER),
            )
            for hit in hits:
                shape = hit.shape
                if not hasattr(shape, "racer_index"):
                    continue
                victim_idx = shape.racer_index
                victim = self.racers[victim_idx]
                if victim is racer or not victim["alive"]:
                    continue
                self.pending_removals.append(victim_idx)
                print(f"  [GUN] {racer['name']} shot {victim['name']}!")
                break  # first hit only

    # ──────────────────────────────────────────────
    # Win conditions
    # ──────────────────────────────────────────────
    def _check_finish_line(self):
        if self.winner is not None:
            return
        for racer in self.racers:
            if not racer["alive"] or racer["state"] == "terminator":
                continue  # terminators can't win by finish line
            coords = self._get_grid_coords(racer["body"].position)
            if coords is None:
                continue
            gx, gy = coords
            if (gx, gy) in self.finish_tiles:
                self.winner = racer["name"]
                print(f"  [WIN] {racer['name']} reached the finish line!")
                return

    def _check_last_alive(self):
        if self.winner is not None:
            return
        alive = [r for r in self.racers if r["alive"]]
        if len(alive) == 1:
            self.winner = alive[0]["name"]
            print(f"  [WIN] {alive[0]['name']} is the last one standing!")
        elif len(alive) == 0:
            # All dead — no winner (stalemate)
            self.winner = None

    # ──────────────────────────────────────────────
    # Deferred removal (prevents pymunk mid-step crash)
    # ──────────────────────────────────────────────
    def _flush_removals(self, space):
        removed = set()
        for idx in self.pending_removals:
            if idx in removed:
                continue
            racer = self.racers[idx]
            if not racer["alive"]:
                continue
            racer["alive"] = False
            body = racer["body"]
            for shape in body.shapes:
                space.remove(shape)
            space.remove(body)
            removed.add(idx)
        self.pending_removals.clear()

    # ──────────────────────────────────────────────
    # Cooldown ticking
    # ──────────────────────────────────────────────
    def _update_cooldowns(self, dt):
        for knife in self.dropped_knives:
            # Mutate in-place via list replacement
            pass
        # Rebuild with decremented cooldowns
        self.dropped_knives = [
            (kx, ky, max(0.0, cd - dt))
            for kx, ky, cd in self.dropped_knives
        ]
        for racer in self.racers:
            if racer["item_cooldown"] > 0:
                racer["item_cooldown"] = max(0.0, racer["item_cooldown"] - dt)
