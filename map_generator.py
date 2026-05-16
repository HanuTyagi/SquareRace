"""
map_generator.py — Map Engine v2: structured room/corridor arenas with metadata.
"""

import collections
import math
import random

from config import (
    GRID_W,
    GRID_H,
    TILE_SIZE,
    FINISH_LINE_MIN_LEN,
    FINISH_LINE_MAX_LEN,
    ITEM_COUNT_PROBS,
    ITEM_BUFFER_MIN,
    ITEM_BUFFER_MAX,
    SPAWN_MODE_CORNER_PROB,
    CORNER_SPAWN_SPLIT_PROB,
    SPAWN_ROOM_W,
    SPAWN_ROOM_H,
    CORNER_ROOM_W,
    CORNER_ROOM_H,
    HUB_ROOM_W,
    HUB_ROOM_H,
    MAIN_CORRIDOR_WIDTH,
    MAIN_PATH_MIN_TURNS,
    MAIN_PATH_MAX_TURNS,
    POCKET_COUNT,
    POCKET_SIZE_MIN,
    POCKET_SIZE_MAX,
    POCKET_MIN_INDEX,
    POCKET_MAX_INDEX_PAD,
    POCKET_FINISH_MIN_DISTANCE_X,
    POCKET_FINISH_MIN_DISTANCE_Y,
    MAP_GEN_MAX_ATTEMPTS,
    MIN_POCKETS_CORNER4,
    MIN_POCKETS_DEFAULT,
    DISCONNECTED_TILE_DEPTH,
)

# Tile types
TILE_FLOOR = 0
TILE_WALL = 1
TILE_ITEM = 2
TILE_FINISH = 3
TILE_SHRINK = 4


# ─────────────────────────────────────────────────────────────
# Generic helpers
# ─────────────────────────────────────────────────────────────
def _neighbors4(x, y):
    for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        yield x + dx, y + dy


def _bfs_path(grid, start, goals):
    """Return shortest path to any goal, or [] if blocked."""
    sx, sy = start
    goal_set = set(goals)
    h, w = len(grid), len(grid[0])
    q = collections.deque([(sx, sy)])
    parent = {(sx, sy): None}

    while q:
        x, y = q.popleft()
        if (x, y) in goal_set:
            path = []
            cur = (x, y)
            while cur is not None:
                path.append(cur)
                cur = parent[cur]
            return list(reversed(path))

        for nx, ny in _neighbors4(x, y):
            # Keep the border ring blocked as permanent outer walls.
            if not (0 < nx < w - 1 and 0 < ny < h - 1):
                continue
            if (nx, ny) in parent:
                continue
            if grid[ny][nx] not in (TILE_FLOOR, TILE_FINISH, TILE_ITEM):
                continue
            parent[(nx, ny)] = (x, y)
            q.append((nx, ny))
    return []


def _make_filled_grid(w, h, value):
    return [[value] * w for _ in range(h)]


def _set_tile(grid, x, y, tile=TILE_FLOOR):
    if 0 < x < len(grid[0]) - 1 and 0 < y < len(grid) - 1:
        grid[y][x] = tile


def _carve_rect(grid, x, y, rw, rh, tile=TILE_FLOOR):
    for yy in range(y, y + rh):
        for xx in range(x, x + rw):
            _set_tile(grid, xx, yy, tile)


def _rect_tiles(x, y, rw, rh):
    return {(xx, yy) for yy in range(y, y + rh) for xx in range(x, x + rw)}


def _can_carve_rect(grid, x, y, rw, rh):
    w = len(grid[0])
    h = len(grid)
    if x <= 1 or y <= 1 or x + rw >= w - 1 or y + rh >= h - 1:
        return False
    for yy in range(y, y + rh):
        for xx in range(x, x + rw):
            if grid[yy][xx] != TILE_WALL:
                return False
    return True


def _line_points(a, b):
    """Axis-aligned inclusive line points between a and b."""
    x1, y1 = a
    x2, y2 = b
    points = []
    if x1 == x2:
        step = 1 if y2 >= y1 else -1
        for y in range(y1, y2 + step, step):
            points.append((x1, y))
    elif y1 == y2:
        step = 1 if x2 >= x1 else -1
        for x in range(x1, x2 + step, step):
            points.append((x, y1))
    return points


def _expand_spine(points):
    spine = []
    for i in range(len(points) - 1):
        seg = _line_points(points[i], points[i + 1])
        if i > 0:
            seg = seg[1:]
        spine.extend(seg)
    return spine


def _carve_corridor_from_spine(grid, spine, width):
    carved = set()
    radius = max(0, width // 2)
    for x, y in spine:
        for yy in range(y - radius, y + radius + 1):
            for xx in range(x - radius, x + radius + 1):
                _set_tile(grid, xx, yy, TILE_FLOOR)
                if 0 < xx < GRID_W - 1 and 0 < yy < GRID_H - 1:
                    carved.add((xx, yy))
    return carved


def _room_center(x, y, rw, rh):
    return x + rw // 2, y + rh // 2


def _spawn_points_in_room(x, y, rw, rh, count):
    cx, cy = _room_center(x, y, rw, rh)
    if count == 1:
        return [(cx, cy)]
    if count == 2:
        return [(cx - 1, cy), (cx + 1, cy)]
    if count == 4:
        return [(cx - 1, cy - 1), (cx + 1, cy - 1), (cx - 1, cy + 1), (cx + 1, cy + 1)]
    pts = []
    for i in range(count):
        pts.append((cx + (i % 2), cy + (i // 2)))
    return pts


def _distance_map_within_region(region_tiles, entrances):
    """BFS distance from nearest entrance to all region tiles."""
    q = collections.deque()
    dist = {}
    region = set(region_tiles)
    for e in entrances:
        if e in region:
            dist[e] = 0
            q.append(e)

    while q:
        x, y = q.popleft()
        for nx, ny in _neighbors4(x, y):
            if (nx, ny) not in region or (nx, ny) in dist:
                continue
            dist[(nx, ny)] = dist[(x, y)] + 1
            q.append((nx, ny))

    # Disconnected tiles (unexpected) get lowest fill priority.
    for t in region:
        dist.setdefault(t, DISCONNECTED_TILE_DEPTH)
    return dist


# ─────────────────────────────────────────────────────────────
# Topology generation
# ─────────────────────────────────────────────────────────────
def _build_spawn_and_hub(grid, spawn_mode_choice):
    """
    Build spawn regions and hub.

    Returns
    -------
    spawn_regions : list[dict]
    spawn_points : list[(x, y)] exactly 4 tiles
    hub_center : (x, y)
    spawn_mode : str
    """
    w, h = GRID_W, GRID_H
    hub_x = (w - HUB_ROOM_W) // 2
    hub_y = int(h * 0.62)
    hub_y = min(max(8, hub_y), h - HUB_ROOM_H - 6)
    _carve_rect(grid, hub_x, hub_y, HUB_ROOM_W, HUB_ROOM_H, TILE_FLOOR)
    hub_center = _room_center(hub_x, hub_y, HUB_ROOM_W, HUB_ROOM_H)

    spawn_regions = []
    spawn_points = []

    if spawn_mode_choice == "single":
        # 80% single shared spawn room.
        sx = (w - SPAWN_ROOM_W) // 2
        sy = h - SPAWN_ROOM_H - 2
        _carve_rect(grid, sx, sy, SPAWN_ROOM_W, SPAWN_ROOM_H, TILE_FLOOR)
        spawn_points = _spawn_points_in_room(sx, sy, SPAWN_ROOM_W, SPAWN_ROOM_H, 4)

        room_center = _room_center(sx, sy, SPAWN_ROOM_W, SPAWN_ROOM_H)
        join_y = hub_center[1] + HUB_ROOM_H // 2
        points = [room_center, (room_center[0], join_y), (hub_center[0], join_y), hub_center]
        _carve_corridor_from_spine(grid, _expand_spine(points), width=2)

        spawn_regions.append(
            {
                "name": "single_spawn",
                "tiles": _rect_tiles(sx, sy, SPAWN_ROOM_W, SPAWN_ROOM_H),
                "entrances": {(room_center[0], sy - 1)},
            }
        )
        return spawn_regions, spawn_points, hub_center, "single"

    # 20% corner mode: B1=4 corners (1 each), B2=2 corners (2 each)
    corners = {
        "tl": (2, 2),
        "tr": (w - CORNER_ROOM_W - 2, 2),
        "bl": (2, h - CORNER_ROOM_H - 2),
        "br": (w - CORNER_ROOM_W - 2, h - CORNER_ROOM_H - 2),
    }

    if spawn_mode_choice == "corner4":
        chosen = ["tl", "tr", "bl", "br"]
        per_corner = 1
        spawn_mode = "corner4"
    else:
        chosen = random.sample(list(corners.keys()), 2)
        per_corner = 2
        spawn_mode = "corner2"

    for key in chosen:
        rx, ry = corners[key]
        _carve_rect(grid, rx, ry, CORNER_ROOM_W, CORNER_ROOM_H, TILE_FLOOR)
        room_center = _room_center(rx, ry, CORNER_ROOM_W, CORNER_ROOM_H)

        # L-shaped branch into hub with right-angle geometry.
        mid_x = room_center[0]
        if room_center[0] < hub_center[0]:
            mid_x = hub_center[0] - random.randint(2, 4)
        elif room_center[0] > hub_center[0]:
            mid_x = hub_center[0] + random.randint(2, 4)
        mid_y = room_center[1] + (1 if room_center[1] < hub_center[1] else -1) * random.randint(4, 7)
        points = [room_center, (room_center[0], mid_y), (mid_x, mid_y), (mid_x, hub_center[1]), hub_center]
        _carve_corridor_from_spine(grid, _expand_spine(points), width=2)

        spawn_regions.append(
            {
                "name": f"spawn_{key}",
                "tiles": _rect_tiles(rx, ry, CORNER_ROOM_W, CORNER_ROOM_H),
                "entrances": {(room_center[0], room_center[1])},
            }
        )
        spawn_points.extend(_spawn_points_in_room(rx, ry, CORNER_ROOM_W, CORNER_ROOM_H, per_corner))

    # Always exactly 4 racers.
    spawn_points = spawn_points[:4]
    return spawn_regions, spawn_points, hub_center, spawn_mode


def _build_finish_and_main_corridor(grid, hub_center):
    """Carve finish chamber and main corridor spine from hub to finish."""
    w, h = GRID_W, GRID_H

    chamber_w = max(8, FINISH_LINE_MAX_LEN + 4)
    chamber_h = 5
    chamber_x = (w - chamber_w) // 2
    chamber_y = 2
    _carve_rect(grid, chamber_x, chamber_y, chamber_w, chamber_h, TILE_FLOOR)

    finish_len = random.randint(FINISH_LINE_MIN_LEN, FINISH_LINE_MAX_LEN)
    finish_y = chamber_y + 1
    finish_start_x = chamber_x + (chamber_w - finish_len) // 2
    finish_tiles = [(finish_start_x + i, finish_y) for i in range(finish_len)]
    for fx, fy in finish_tiles:
        _set_tile(grid, fx, fy, TILE_FINISH)

    finish_approach = (finish_start_x + finish_len // 2, chamber_y + chamber_h - 1)

    # 1–2 turns path from hub to finish approach.
    turns = random.randint(MAIN_PATH_MIN_TURNS, MAIN_PATH_MAX_TURNS)
    points = [hub_center]
    if turns >= 1:
        y1 = random.randint(max(6, finish_approach[1] + 3), max(7, hub_center[1] - 7))
        points.append((hub_center[0], y1))
    if turns >= 2:
        x2 = random.randint(5, w - 6)
        points.append((x2, points[-1][1]))
    points.append((finish_approach[0], points[-1][1]))
    points.append(finish_approach)

    spine = _expand_spine(points)
    corridor_tiles = _carve_corridor_from_spine(grid, spine, MAIN_CORRIDOR_WIDTH)

    # Keep a clean finish approach corridor.
    _carve_corridor_from_spine(grid, _line_points(finish_approach, (finish_approach[0], finish_y + 1)), MAIN_CORRIDOR_WIDTH)

    return finish_tiles, spine, corridor_tiles, (chamber_x, chamber_y, chamber_w, chamber_h)


def _place_pockets(grid, spine, finish_anchor):
    """Attach dead-end room pockets to the main corridor."""
    pockets = []
    if len(spine) < 12:
        return pockets

    min_idx = min(POCKET_MIN_INDEX, len(spine) - 2)
    max_idx = max(min_idx, len(spine) - POCKET_MAX_INDEX_PAD)
    candidate_indices = list(range(min_idx, max_idx))
    random.shuffle(candidate_indices)

    for idx in candidate_indices:
        if len(pockets) >= POCKET_COUNT:
            break
        cx, cy = spine[idx]

        prev_pt = spine[max(0, idx - 1)]
        next_pt = spine[min(len(spine) - 1, idx + 1)]
        dx = next_pt[0] - prev_pt[0]
        dy = next_pt[1] - prev_pt[1]
        if dx != 0:
            dirs = [(0, -1), (0, 1)]
        else:
            dirs = [(-1, 0), (1, 0)]

        random.shuffle(dirs)
        placed = False
        for sx, sy in dirs:
            ex, ey = cx + sx * (MAIN_CORRIDOR_WIDTH // 2 + 1), cy + sy * (MAIN_CORRIDOR_WIDTH // 2 + 1)
            if not (1 < ex < GRID_W - 2 and 1 < ey < GRID_H - 2):
                continue

            room_w = random.randint(POCKET_SIZE_MIN, POCKET_SIZE_MAX)
            room_h = random.randint(POCKET_SIZE_MIN, POCKET_SIZE_MAX)

            if sx == 1:
                rx, ry = ex + 1, ey - room_h // 2
            elif sx == -1:
                rx, ry = ex - room_w, ey - room_h // 2
            elif sy == 1:
                rx, ry = ex - room_w // 2, ey + 1
            else:  # sy == -1
                rx, ry = ex - room_w // 2, ey - room_h

            if not _can_carve_rect(grid, rx, ry, room_w, room_h):
                continue

            # Keep near-finish pockets possible, but not directly inside finish chamber.
            if (
                abs((rx + room_w // 2) - finish_anchor[0]) < POCKET_FINISH_MIN_DISTANCE_X
                and abs((ry + room_h // 2) - finish_anchor[1]) < POCKET_FINISH_MIN_DISTANCE_Y
            ):
                continue

            _set_tile(grid, ex, ey, TILE_FLOOR)
            _carve_rect(grid, rx, ry, room_w, room_h, TILE_FLOOR)
            room_tiles = _rect_tiles(rx, ry, room_w, room_h)
            room_tiles.add((ex, ey))

            pockets.append(
                {
                    "entrances": {(ex, ey)},
                    "tiles": room_tiles,
                    "corridor_index": idx,
                }
            )
            placed = True
            break

        if placed:
            continue

    return pockets


def _place_items(grid, spawn_start, finish_tiles):
    """Place 0-3 item tiles in a buffer zone around shortest path."""
    path = _bfs_path(grid, spawn_start, finish_tiles)
    if not path:
        return []

    path_set = set(path)
    buffer_radius = random.randint(ITEM_BUFFER_MIN, ITEM_BUFFER_MAX)

    candidates = []
    for y in range(1, GRID_H - 1):
        for x in range(1, GRID_W - 1):
            if grid[y][x] != TILE_FLOOR or (x, y) in path_set:
                continue
            if any(abs(x - px) + abs(y - py) <= buffer_radius for px, py in path):
                candidates.append((x, y))

    random.shuffle(candidates)

    r = random.random()
    cumulative = 0.0
    count = 0
    for item_count, prob in sorted(ITEM_COUNT_PROBS.items()):
        cumulative += prob
        if r < cumulative:
            count = item_count
            break

    placed = []
    for x, y in candidates[:count]:
        grid[y][x] = TILE_ITEM
        placed.append((x, y))
    return placed


def _validate_paths(grid, spawn_points, finish_tiles):
    for sp in spawn_points:
        if not _bfs_path(grid, sp, finish_tiles):
            return False
    return True


def _build_region_metadata(spawn_regions, pockets, spine, finish_tiles, spawn_mode):
    """Augment regions with depth ordering and ranking features."""
    finish_set = set(finish_tiles)

    # Compute spine index lookup.
    spine_index = {tile: i for i, tile in enumerate(spine)}

    def nearest_spine_index(tile):
        if tile in spine_index:
            return spine_index[tile]
        best_idx = None
        best_dist = 10**9
        for idx, sp in enumerate(spine):
            d = abs(sp[0] - tile[0]) + abs(sp[1] - tile[1])
            if d < best_dist:
                best_dist = d
                best_idx = idx
        return best_idx

    def finish_distance_score(region):
        indices = []
        for e in region["entrances"]:
            i = region.get("corridor_index")
            if i is None:
                i = nearest_spine_index(e)
            if i is not None:
                indices.append(len(spine) - 1 - i)
        return max(indices) if indices else len(spine)

    for region in spawn_regions:
        region["depth_map"] = _distance_map_within_region(region["tiles"], region["entrances"])
        region["finish_distance"] = finish_distance_score(region)
        region["near_finish"] = any(t in finish_set for t in region["tiles"])

    for p in pockets:
        p["depth_map"] = _distance_map_within_region(p["tiles"], p["entrances"])
        p["finish_distance"] = finish_distance_score(p)
        p["near_finish"] = p["finish_distance"] <= max(3, int(len(spine) * 0.2))

    return {
        "spawn_mode": spawn_mode,
        "spawn_regions": spawn_regions,
        "pockets": pockets,
        "main_corridor_spine": spine,
        "finish_tiles": list(finish_tiles),
    }


def generate_arena():
    """
    Generate a structured arena and metadata for staged shrinking.

    Returns
    -------
    grid : list[list[int]]
    spawn_positions_px : list[(float, float)]
    finish_tiles : list[(int, int)]
    item_tiles : list[(int, int)]
    map_meta : dict
    """
    w, h = GRID_W, GRID_H

    if random.random() >= SPAWN_MODE_CORNER_PROB:
        spawn_mode_choice = "single"
    else:
        spawn_mode_choice = "corner4" if random.random() < CORNER_SPAWN_SPLIT_PROB else "corner2"

    attempts = MAP_GEN_MAX_ATTEMPTS
    for _ in range(attempts):
        grid = _make_filled_grid(w, h, TILE_WALL)

        spawn_regions, spawn_points, hub_center, spawn_mode = _build_spawn_and_hub(grid, spawn_mode_choice)
        finish_tiles, spine, _, finish_chamber = _build_finish_and_main_corridor(grid, hub_center)
        pockets = _place_pockets(grid, spine, finish_tiles[0])

        min_pockets = MIN_POCKETS_CORNER4 if spawn_mode == "corner4" else MIN_POCKETS_DEFAULT
        if len(pockets) < min_pockets:
            continue

        if not _validate_paths(grid, spawn_points, finish_tiles):
            continue

        item_tiles = _place_items(grid, spawn_points[0], finish_tiles)

        spawn_positions_px = [((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE) for x, y in spawn_points]
        map_meta = _build_region_metadata(spawn_regions, pockets, spine, finish_tiles, spawn_mode)
        map_meta["finish_chamber"] = finish_chamber

        return grid, spawn_positions_px, finish_tiles, item_tiles, map_meta

    raise RuntimeError(
        f"Failed to generate a valid Map Engine v2 arena after {MAP_GEN_MAX_ATTEMPTS} attempts "
        f"(spawn mode choice: {spawn_mode_choice})."
    )
