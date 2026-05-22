"""
game_mechanics.py — Modules C + D: weapons, blockers, shrink, and win logic.

Manages:
  - Typed item pickup (knife / gun)
  - Knife: melee elimination on actual racer contact, cooldown drop
  - Gun (Terminator): state change, periodic raycast firing, elimination on hit
  - Region-based shrink pressure and moving blockers
  - Win condition: finish-line crossing only
  - Deferred body removal queue (safe mid-step handling)
"""

import math
import pymunk

from config import (
    TILE_SIZE, SQUARE_SIZE, FPS,
    KNIFE_COOLDOWN_SEC, KNIFE_RANGE_MULTIPLIER,
    GUN_FIRE_INTERVAL, GUN_RAY_LENGTH, RAYCAST_RADIUS,
    COLOR_TERMINATOR,
    MAX_RACE_SECONDS,
    MOVING_BLOCKER_OPEN_SEC,
    MOVING_BLOCKER_CLOSED_SEC,
)
from physics_engine import CAT_RACER, CAT_WALL, add_wall_tile
from map_generator import TILE_FLOOR, TILE_WALL, TILE_FINISH, TILE_SHRINK
from shrink_engine import ShrinkEngine


class GameState:
    """
    Mutable game state container, updated each frame by the simulation loop.

    Parameters
    ----------
    item_tiles : list[dict] | list[tuple[int, int]]
        Preferred format is [{"tile": (x, y), "item_type": "knife"|"gun"}, ...].
        Legacy tuple-only entries default to knife pickups.
    """

    def __init__(self, racers, grid, finish_tiles, item_tiles, map_meta=None):
        self.racers = racers
        self.grid = grid
        self.finish_tiles = set(finish_tiles)
        self.item_spawns = {
            tuple(item["tile"]): item["item_type"]
            for item in item_tiles
            if isinstance(item, dict) and "tile" in item and "item_type" in item
        }
        if not self.item_spawns:
            self.item_spawns = {tuple(t): "knife" for t in item_tiles}
        self.pending_removals = []                 # (racer_index,) queued for removal
        self.dropped_knives = []                   # [(grid_x, grid_y, cooldown_remaining)]
        self.winner = None                         # racer name or None
        self.frame_count = 0
        self.elapsed_sec = 0.0
        self.map_meta = map_meta or {}
        self.shrink_engine = ShrinkEngine(self.map_meta)
        self.shrunk_tiles = set()
        self.newly_shrunk_tiles = []
        self.moving_blockers = list(self.map_meta.get("moving_blockers", []))
        self.blocker_time = 0.0
        self.active_blockers = {}                  # {(x, y): (body, shape)}
        self.active_blocker_tiles = []
        self.stats = {
            "item_pickups": 0,
            "knife_kills": 0,
            "gun_kills": 0,
            "shrink_tiles": 0,
            "blocker_closures": 0,
        }

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
        self._update_moving_blockers(dt, space)
        self._check_knife_collisions(space)
        self._fire_guns(space)
        # Uses staged region shrink for pressure.
        self._update_shrink(dt, space)
        self._check_finish_line()
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
            self.stats["shrink_tiles"] += 1
            add_wall_tile(space, x, y)

            # Remove consumed item if shrink covers it.
            if (x, y) in self.item_spawns:
                self.item_spawns.pop((x, y), None)

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
    # Moving blockers
    # ──────────────────────────────────────────────
    def _update_moving_blockers(self, dt, space):
        self.active_blocker_tiles = []
        if not self.moving_blockers:
            return

        self.blocker_time += dt
        cycle = MOVING_BLOCKER_OPEN_SEC + MOVING_BLOCKER_CLOSED_SEC
        if cycle <= 0:
            return

        for blocker in self.moving_blockers:
            x, y = blocker["tile"]
            phase = (self.blocker_time + blocker.get("phase_offset", 0.0)) % cycle
            should_block = phase >= MOVING_BLOCKER_OPEN_SEC
            key = (x, y)

            if should_block:
                if key not in self.active_blockers:
                    self.active_blockers[key] = add_wall_tile(space, x, y)
                    self.stats["blocker_closures"] += 1
                self.active_blocker_tiles.append(key)
            elif key in self.active_blockers:
                body, shape = self.active_blockers.pop(key)
                try:
                    space.remove(shape, body)
                except (AssertionError, ValueError):
                    print(f"  [BLOCKER] Failed to remove moving blocker at {key}.")

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
            item_type = self.item_spawns.get((gx, gy))
            if item_type:
                if item_type == "knife":
                    racer["held_item"] = "knife"
                elif item_type == "gun":
                    racer["held_item"] = "gun"
                    racer["state"] = "terminator"
                    racer["draw_color"] = COLOR_TERMINATOR
                    racer["gun_timer"] = GUN_FIRE_INTERVAL
                self.stats["item_pickups"] += 1
                # Consume item
                self.item_spawns.pop((gx, gy), None)
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
    def _check_knife_collisions(self, space):
        alive = [r for r in self.racers if r["alive"]]
        for attacker in alive:
            if attacker["held_item"] != "knife":
                continue
            ax, ay = attacker["body"].position
            knife_range = SQUARE_SIZE * KNIFE_RANGE_MULTIPLIER
            for victim in alive:
                if victim is attacker:
                    continue
                vx, vy = victim["body"].position
                if math.hypot(ax - vx, ay - vy) > knife_range:
                    continue
                wall_hit = space.segment_query_first(
                    (ax, ay),
                    (vx, vy),
                    RAYCAST_RADIUS,
                    pymunk.ShapeFilter(mask=CAT_WALL),
                )
                if wall_hit is not None:
                    continue
                idx = self.racers.index(victim)
                self.pending_removals.append(idx)
                self.dropped_knives.append((int(ax // TILE_SIZE), int(ay // TILE_SIZE), KNIFE_COOLDOWN_SEC))
                attacker["held_item"] = None
                self.stats["knife_kills"] += 1
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
                (px, py), (end_x, end_y), RAYCAST_RADIUS,
                pymunk.ShapeFilter(mask=CAT_RACER | CAT_WALL),
            )
            hit = None
            for result in hits:
                if result.shape in racer["body"].shapes:
                    continue
                if hit is None or result.alpha < hit.alpha:
                    hit = result
            if hit is None or not hasattr(hit.shape, "racer_index"):
                continue
            victim_idx = hit.shape.racer_index
            victim = self.racers[victim_idx]
            if not victim["alive"]:
                continue
            self.pending_removals.append(victim_idx)
            self.stats["gun_kills"] += 1
            print(f"  [GUN] {racer['name']} shot {victim['name']}!")

    # ──────────────────────────────────────────────
    # Win conditions
    # ──────────────────────────────────────────────
    def _check_finish_line(self):
        if self.winner is not None:
            return
        for racer in self.racers:
            if not racer["alive"]:
                continue
            coords = self._get_grid_coords(racer["body"].position)
            if coords is None:
                continue
            gx, gy = coords
            if (gx, gy) in self.finish_tiles:
                self.winner = racer["name"]
                print(f"  [WIN] {racer['name']} reached the finish line!")
                return

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
        self.dropped_knives = [
            (kx, ky, max(0.0, cd - dt))
            for kx, ky, cd in self.dropped_knives
        ]
        for racer in self.racers:
            if racer["item_cooldown"] > 0:
                racer["item_cooldown"] = max(0.0, racer["item_cooldown"] - dt)

    def quality_metrics(self):
        """Return aggregate metrics for race selection heuristics."""
        return {
            **self.stats,
            "duration_sec": self.elapsed_sec,
            "winner": self.winner,
        }
