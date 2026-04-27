"""
map_generator.py — Module A: Validated Slate Arena Generator.

Generates a grid-based map with:
  - Border walls
  - Edge-anchored + central rectangular obstacles
  - Random spawn area with carved buffer
  - Wall-anchored finish line (2-4 tiles, validated reachable via BFS)
  - Risk/reward item tiles placed in a buffer zone around the shortest path
"""

import random
import math
import collections

from config import (
    GRID_W, GRID_H, TILE_SIZE,
    NUM_EDGE_OBSTACLES, NUM_CENTER_OBSTACLES,
    OBSTACLE_SIZE_MIN, OBSTACLE_SIZE_MAX,
    FINISH_LINE_MIN_LEN, FINISH_LINE_MAX_LEN,
    MIN_FINISH_DISTANCE,
    SPAWN_BUFFER_W, SPAWN_BUFFER_H,
    ITEM_COUNT_PROBS, ITEM_BUFFER_MIN, ITEM_BUFFER_MAX,
)

# Tile types
TILE_FLOOR  = 0
TILE_WALL   = 1
TILE_ITEM   = 2
TILE_FINISH = 3


def _bfs_path(grid, start, goal):
    """Return shortest path (list of (x,y)) from start to goal, or [] if blocked."""
    sx, sy = start
    gx, gy = goal
    h, w = len(grid), len(grid[0])
    queue = collections.deque([(sx, sy, [(sx, sy)])])
    seen = {(sx, sy)}
    while queue:
        x, y, path = queue.popleft()
        if x == gx and y == gy:
            return path
        for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            nx, ny = x + dx, y + dy
            if 0 < nx < w - 1 and 0 < ny < h - 1 and (nx, ny) not in seen:
                if grid[ny][nx] in (TILE_FLOOR, TILE_FINISH):
                    seen.add((nx, ny))
                    queue.append((nx, ny, path + [(nx, ny)]))
    return []


def _place_border_walls(grid, w, h):
    for x in range(w):
        grid[0][x] = TILE_WALL
        grid[h - 1][x] = TILE_WALL
    for y in range(h):
        grid[y][0] = TILE_WALL
        grid[y][w - 1] = TILE_WALL


def _place_edge_obstacles(grid, w, h):
    for _ in range(NUM_EDGE_OBSTACLES):
        side = random.choice(("top", "bottom", "left", "right"))
        bw = random.randint(OBSTACLE_SIZE_MIN, OBSTACLE_SIZE_MAX)
        bh = random.randint(OBSTACLE_SIZE_MIN, OBSTACLE_SIZE_MAX)
        if side == "top":
            bx, by = random.randint(1, w - bw - 1), 1
        elif side == "bottom":
            bx, by = random.randint(1, w - bw - 1), h - bh - 1
        elif side == "left":
            bx, by = 1, random.randint(1, h - bh - 1)
        else:
            bx, by = w - bw - 1, random.randint(1, h - bh - 1)
        for y in range(by, by + bh):
            for x in range(bx, bx + bw):
                if 0 < x < w - 1 and 0 < y < h - 1:
                    grid[y][x] = TILE_WALL


def _place_center_obstacles(grid, w, h):
    for _ in range(NUM_CENTER_OBSTACLES):
        bw = random.randint(OBSTACLE_SIZE_MIN, OBSTACLE_SIZE_MAX - 1)
        bh = random.randint(OBSTACLE_SIZE_MIN, OBSTACLE_SIZE_MAX - 1)
        bx = random.randint(1, w - bw - 1)
        by = random.randint(1, h - bh - 4)
        for y in range(by, by + bh):
            for x in range(bx, bx + bw):
                if 0 < x < w - 1 and 0 < y < h - 1:
                    grid[y][x] = TILE_WALL


def _carve_spawn(grid, w, h):
    """Carve a clear buffer zone at a random position. Returns spawn tile (x, y)."""
    sx = random.randint(2, w - SPAWN_BUFFER_W)
    sy = random.randint(2, h - SPAWN_BUFFER_H)
    for y in range(sy - 1, sy + SPAWN_BUFFER_H - 1):
        for x in range(sx - 1, sx + SPAWN_BUFFER_W - 1):
            if 0 < x < w - 1 and 0 < y < h - 1:
                grid[y][x] = TILE_FLOOR
    return sx, sy


def _find_anchored_tiles(grid, w, h):
    """Return floor tiles adjacent to at least one wall (candidates for finish line)."""
    anchored = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if grid[y][x] == TILE_FLOOR:
                walls = sum(
                    1 for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))
                    if grid[y + dy][x + dx] == TILE_WALL
                )
                if walls >= 1:
                    anchored.append((x, y))
    return anchored


def _place_finish_line(grid, anchored, spawn_x, spawn_y, w, h):
    """Try to place a 2-4 tile finish line. Returns list of tiles or None."""
    # Prefer tiles far from spawn
    far = [t for t in anchored if math.hypot(t[0] - spawn_x, t[1] - spawn_y) >= MIN_FINISH_DISTANCE]
    candidates = far if far else anchored
    if not candidates:
        return None

    random.shuffle(candidates)
    for fx, fy in candidates:
        finish_len = random.randint(FINISH_LINE_MIN_LEN, FINISH_LINE_MAX_LEN)
        placements = []
        # Try all 4 directions
        for gen in (
            lambda l: [(fx + d, fy) for d in range(l)],
            lambda l: [(fx - d, fy) for d in range(l)],
            lambda l: [(fx, fy + d) for d in range(l)],
            lambda l: [(fx, fy - d) for d in range(l)],
        ):
            tiles = gen(finish_len)
            if all(0 < tx < w - 1 and 0 < ty < h - 1 and grid[ty][tx] == TILE_FLOOR for tx, ty in tiles):
                placements.append(tiles)
        if placements:
            chosen = random.choice(placements)
            for tx, ty in chosen:
                grid[ty][tx] = TILE_FINISH
            return chosen
    return None


def _place_items(grid, spawn_x, spawn_y, finish_tiles, w, h):
    """Place 0-3 item tiles in a buffer zone around the shortest path."""
    if not finish_tiles:
        return
    path = _bfs_path(grid, (spawn_x + 1, spawn_y), finish_tiles[0])
    if not path:
        return
    path_set = set(path)
    buffer_radius = random.randint(ITEM_BUFFER_MIN, ITEM_BUFFER_MAX)
    buffer_zone = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if grid[y][x] == TILE_FLOOR and (x, y) not in path_set:
                for px, py in path:
                    if abs(x - px) + abs(y - py) <= buffer_radius:
                        buffer_zone.append((x, y))
                        break
    random.shuffle(buffer_zone)

    # Weighted random item count
    r = random.random()
    cumulative = 0.0
    num_items = 0
    for count, prob in sorted(ITEM_COUNT_PROBS.items()):
        cumulative += prob
        if r < cumulative:
            num_items = count
            break

    for i in range(min(num_items, len(buffer_zone))):
        ix, iy = buffer_zone[i]
        grid[iy][ix] = TILE_ITEM


def generate_arena():
    """
    Generate a fully validated arena.

    Returns
    -------
    grid : list[list[int]]
        2D tile grid (TILE_FLOOR / TILE_WALL / TILE_ITEM / TILE_FINISH).
    spawn_center : tuple[float, float]
        Pixel-space center of the 4-racer spawn area.
    finish_tiles : list[tuple[int, int]]
        Grid coordinates of all finish-line tiles.
    item_tiles : list[tuple[int, int]]
        Grid coordinates of all item tiles.
    """
    w, h = GRID_W, GRID_H
    while True:
        grid = [[TILE_FLOOR] * w for _ in range(h)]
        _place_border_walls(grid, w, h)
        _place_edge_obstacles(grid, w, h)
        _place_center_obstacles(grid, w, h)
        spawn_x, spawn_y = _carve_spawn(grid, w, h)

        anchored = _find_anchored_tiles(grid, w, h)
        if not anchored:
            continue

        finish_tiles = _place_finish_line(grid, anchored, spawn_x, spawn_y, w, h)
        if finish_tiles is None:
            continue

        # Strict multi-path validation: every finish tile must be reachable
        all_ok = True
        for tx, ty in finish_tiles:
            if not _bfs_path(grid, (spawn_x + 1, spawn_y), (tx, ty)):
                all_ok = False
                break
        if not all_ok:
            continue

        _place_items(grid, spawn_x, spawn_y, finish_tiles, w, h)

        # Collect item tile coords
        item_tiles = []
        for y in range(h):
            for x in range(w):
                if grid[y][x] == TILE_ITEM:
                    item_tiles.append((x, y))

        spawn_center = ((spawn_x + 1.5) * TILE_SIZE, (spawn_y + 0.5) * TILE_SIZE)
        return grid, spawn_center, finish_tiles, item_tiles
