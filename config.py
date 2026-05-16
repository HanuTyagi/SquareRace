"""
config.py — All constants for the Square Race Video Generator.

Central source of truth for grid dimensions, physics parameters,
colors, weapon probabilities, and timing values.
"""

import math

# ─── Grid & Resolution ──────────────────────────────────────────
TILE_SIZE = 20
GRID_W, GRID_H = 32, 50                     # tiles
WIDTH  = GRID_W * TILE_SIZE                  # 640 px
HEIGHT = GRID_H * TILE_SIZE                  # 1000 px  (≈ 9:14, close to 9:16)

# ─── Physics ────────────────────────────────────────────────────
FPS = 60
CONSTANT_SPEED   = 80       # px / second — forced magnitude every frame
SQUARE_SIZE      = 20       # px side-length of each racer
RACER_MASS       = 1
RACER_ELASTICITY = 1.0
RACER_FRICTION   = 0.0
WALL_ELASTICITY  = 1.0
WALL_FRICTION    = 0.0
SCATTER_OFFSET_DEG = 25     # angular offset per racer at spawn

# ─── Visual Trail ───────────────────────────────────────────────
TRAIL_LENGTH     = 15       # frames of trail history
TRAIL_ALPHA_MAX  = 180      # peak alpha for newest trail segment
TRAIL_MIN_SCALE  = 0.6      # smallest trail square is 60 % of SQUARE_SIZE

# ─── Colour Palette (Slate Aesthetic) ───────────────────────────
COLOR_WALL       = (60, 65, 80)
COLOR_PATH       = (25, 25, 30)
COLOR_CHECKER_1  = (220, 220, 220)
COLOR_CHECKER_2  = (150, 150, 150)
COLOR_FINISH_1   = (255, 150, 50)
COLOR_FINISH_2   = (50, 50, 50)
COLOR_DEATH_ZONE = (180, 30, 30)
COLOR_TERMINATOR = (160, 60, 60)
COLOR_KNIFE      = (200, 200, 210)
COLOR_HUD_TEXT   = (255, 255, 255)
COLOR_SHRINK     = (160, 40, 40)

RACER_COLORS = [
    (255, 50, 50),     # Red
    (50, 50, 255),     # Blue
    (50, 255, 50),     # Green
    (255, 255, 50),    # Yellow
]
RACER_NAMES = ["Red", "Blue", "Green", "Yellow"]

# ─── Map Generation ────────────────────────────────────────────
NUM_EDGE_OBSTACLES   = 9
NUM_CENTER_OBSTACLES = 4
OBSTACLE_SIZE_MIN    = 2     # tiles
OBSTACLE_SIZE_MAX    = 6     # tiles (edge), 5 (center)
FINISH_LINE_MIN_LEN  = 2     # tiles
FINISH_LINE_MAX_LEN  = 4
MIN_FINISH_DISTANCE  = 12    # Euclidean tile distance from spawn
SPAWN_BUFFER_W       = 6     # tiles carved open around spawn
SPAWN_BUFFER_H       = 3

# v2 map generation (corridor + pockets)
SPAWN_MODE_CORNER_PROB = 0.20     # 20%: corner spawns, 80%: single spawn
CORNER_SPAWN_SPLIT_PROB = 0.50    # 50%: 4 corners, 50%: 2 corners
SPAWN_ROOM_W = 6
SPAWN_ROOM_H = 4
CORNER_ROOM_W = 6
CORNER_ROOM_H = 4
HUB_ROOM_W = 6
HUB_ROOM_H = 4
MAIN_CORRIDOR_WIDTH = 3
MAIN_PATH_MIN_TURNS = 1
MAIN_PATH_MAX_TURNS = 2
POCKET_COUNT = 6
POCKET_SIZE_MIN = 4
POCKET_SIZE_MAX = 8
POCKET_MIN_INDEX = 4            # avoid pockets too close to spawn hub
POCKET_MAX_INDEX_PAD = 6        # keep pockets away from finish
POCKET_FINISH_MIN_DISTANCE_X = 2
POCKET_FINISH_MIN_DISTANCE_Y = 3
MAP_GEN_MAX_ATTEMPTS = 300
MIN_POCKETS_CORNER4 = 1
MIN_POCKETS_DEFAULT = 2

# ─── Item Spawning Probabilities ────────────────────────────────
ITEM_COUNT_PROBS = {0: 0.40, 1: 0.30, 2: 0.20, 3: 0.10}
ITEM_BUFFER_MIN  = 3         # min Manhattan distance from path
ITEM_BUFFER_MAX  = 7

# ─── Weapon System ──────────────────────────────────────────────
WEAPON_KNIFE_PROB    = 0.65
WEAPON_GUN_PROB      = 0.35  # 1 - knife
KNIFE_COOLDOWN_SEC   = 2.0   # seconds after use before re-pickup
GUN_FIRE_INTERVAL    = 2.0   # seconds between Terminator shots
GUN_RAY_LENGTH       = 600   # px — max raycast distance

# ─── Shrink Mechanics (region-based) ────────────────────────────
SHRINK_START_SEC          = 8.0
SHRINK_CORRIDOR_STEP_TILES = 4
SHRINK_STEP_PAUSE_SEC     = 1.5
SHRINK_POCKET_PAUSE_SEC   = 1.2
SHRINK_POCKET_BATCH       = 2
SHRINK_MIN_FINISH_GUARD_TILES = 4
SHRINK_FINISH_GUARD_RATIO = 0.12

# ─── Pressure Mechanics ────────────────────────────────────────
MAX_RACE_SECONDS     = 90    # hard cutoff → discard simulation
DEATH_ZONE_START_SEC = 15    # seconds before the death wall starts moving
DEATH_ZONE_SPEED     = 15    # px / second downward

# ─── Video Pipeline ────────────────────────────────────────────
VIDEO_CODEC   = "mp4v"
VIDEO_EXT     = ".mp4"
MAX_ATTEMPTS  = 10           # retries before giving up on one video
