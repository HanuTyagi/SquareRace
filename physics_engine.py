"""
physics_engine.py — Module B: pymunk space, racer creation, wall bodies.

Handles:
  - Creating the pymunk Space with zero gravity
  - Adding static wall bodies from the grid
  - Creating the 4 racer bodies with initial scatter velocities
  - Constant-speed enforcement per frame
  - Collision category/filter setup for raycasts
"""

import pymunk
import math
import random

from config import (
    TILE_SIZE, GRID_W, GRID_H, FPS,
    SQUARE_SIZE, RACER_MASS, RACER_ELASTICITY, RACER_FRICTION,
    WALL_ELASTICITY, WALL_FRICTION,
    CONSTANT_SPEED, SCATTER_OFFSET_DEG,
    RACER_COLORS, RACER_NAMES, TRAIL_LENGTH,
)
from map_generator import TILE_WALL

# Collision categories (bitmask)
CAT_WALL  = 0b0001
CAT_RACER = 0b0010
CAT_RAY   = 0b0100


def create_space():
    """Create a zero-gravity pymunk space."""
    space = pymunk.Space()
    space.gravity = (0, 0)
    return space


def add_walls(space, grid):
    """Create static pymunk bodies for every wall tile in the grid."""
    for y in range(GRID_H):
        for x in range(GRID_W):
            if grid[y][x] == TILE_WALL:
                add_wall_tile(space, x, y)


def add_wall_tile(space, x, y):
    """Add one static wall tile body to pymunk space."""
    body = pymunk.Body(body_type=pymunk.Body.STATIC)
    body.position = (
        x * TILE_SIZE + TILE_SIZE / 2,
        y * TILE_SIZE + TILE_SIZE / 2,
    )
    shape = pymunk.Poly.create_box(body, (TILE_SIZE, TILE_SIZE))
    shape.elasticity = WALL_ELASTICITY
    shape.friction = WALL_FRICTION
    shape.filter = pymunk.ShapeFilter(categories=CAT_WALL)
    space.add(body, shape)


def create_racers(space, spawn_center):
    """
    Spawn 4 racers at the given pixel center with diverging angles.

    Returns a list of racer dicts:
        {body, shape, color, draw_color, name, history, alive,
         state, held_item, item_cooldown, gun_timer}
    """
    racers = []
    base_angle = random.uniform(0, math.pi * 2)

    spawn_positions = None
    if isinstance(spawn_center, list):
        spawn_positions = spawn_center

    for i in range(4):
        moment = pymunk.moment_for_box(RACER_MASS, (SQUARE_SIZE, SQUARE_SIZE))
        body = pymunk.Body(RACER_MASS, moment)
        if spawn_positions and i < len(spawn_positions):
            body.position = spawn_positions[i]
        else:
            offset_x = (i - 1.5) * (SQUARE_SIZE + 2)
            body.position = (spawn_center[0] + offset_x, spawn_center[1])

        shape = pymunk.Poly.create_box(body, (SQUARE_SIZE, SQUARE_SIZE))
        shape.elasticity = RACER_ELASTICITY
        shape.friction = RACER_FRICTION
        shape.filter = pymunk.ShapeFilter(categories=CAT_RACER, mask=CAT_WALL | CAT_RACER)
        # Tag the shape so collision handlers can identify the racer
        shape.racer_index = i
        space.add(body, shape)

        angle = base_angle + math.radians(i * SCATTER_OFFSET_DEG)
        body.velocity = (
            math.cos(angle) * CONSTANT_SPEED,
            math.sin(angle) * CONSTANT_SPEED,
        )

        racers.append({
            "body": body,
            "shape": shape,
            "color": RACER_COLORS[i],
            "draw_color": RACER_COLORS[i],   # may change for terminator
            "name": RACER_NAMES[i],
            "history": [],
            "alive": True,
            "state": "normal",        # normal | terminator
            "held_item": None,        # None | "knife" | "gun"
            "item_cooldown": 0.0,     # seconds remaining before knife re-pickup
            "gun_timer": 0.0,         # seconds until next shot
        })

    return racers


def enforce_constant_speed(racers):
    """Normalize velocity magnitude of every alive racer to CONSTANT_SPEED."""
    for racer in racers:
        if not racer["alive"]:
            continue
        v = racer["body"].velocity
        if v.length > 0:
            racer["body"].velocity = v.normalized() * CONSTANT_SPEED


def update_trails(racers):
    """Append current position to each racer's trail history."""
    for racer in racers:
        if not racer["alive"]:
            continue
        pos = racer["body"].position
        racer["history"].append((pos.x, pos.y))
        if len(racer["history"]) > TRAIL_LENGTH:
            racer["history"].pop(0)


def step(space):
    """Advance physics by one frame."""
    space.step(1.0 / FPS)
