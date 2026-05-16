"""Staged region-based shrink/fill engine."""

from collections import deque

from config import (
    SHRINK_START_SEC,
    SHRINK_CORRIDOR_STEP_TILES,
    SHRINK_STEP_PAUSE_SEC,
    SHRINK_POCKET_PAUSE_SEC,
    SHRINK_POCKET_BATCH,
)


class ShrinkEngine:
    """
    Region-based staged shrink:
      spawn_fill -> pocket_fill -> corridor_advance -> pocket_fill -> ...
    """

    def __init__(self, map_meta):
        self.meta = map_meta or {}
        self.time = 0.0
        self.pause = 0.0

        self.filled = set()
        self.frontier = set()

        self.spawn_regions = list(self.meta.get("spawn_regions", []))
        self.pockets = list(self.meta.get("pockets", []))
        self.spine = list(self.meta.get("main_corridor_spine", []))
        self.finish_tiles = set(self.meta.get("finish_tiles", []))

        self._spawn_fill_queue = deque(self._region_fill_order(self.spawn_regions))
        self._pocket_fill_queues = {
            idx: deque(self._region_fill_order([p])) for idx, p in enumerate(self.pockets)
        }
        self._pocket_filled = set()

        self._corridor_index = 0
        self._state = "waiting_start"

    @staticmethod
    def _region_fill_order(regions):
        order = []
        for region in regions:
            depth_map = region.get("depth_map", {})
            entries = list(region.get("tiles", []))
            # Fill deep -> entrance to push racers outward.
            entries.sort(key=lambda t: (depth_map.get(t, -1), t[1], t[0]), reverse=True)
            order.extend(entries)
        return order

    @staticmethod
    def _manhattan(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def _frontier_distance(self, region):
        if not self.frontier:
            return 0
        entrances = region.get("entrances", [])
        best = 10**9
        for e in entrances:
            for f in self.frontier:
                best = min(best, self._manhattan(e, f))
        return best if best < 10**9 else 0

    def _rank_pockets(self):
        ranked = []
        for idx, pocket in enumerate(self.pockets):
            if idx in self._pocket_filled:
                continue
            queue = self._pocket_fill_queues[idx]
            if not queue:
                self._pocket_filled.add(idx)
                continue
            finish_distance = pocket.get("finish_distance", 0)
            boundary_dist = self._frontier_distance(pocket)
            ranked.append((idx, finish_distance, boundary_dist))

        # Primary: farther from finish first (desc)
        # Secondary: closer to current boundary/front (asc)
        ranked.sort(key=lambda x: (-x[1], x[2], x[0]))
        return ranked

    def _fill_queue(self, queue, limit):
        newly = []
        while queue and len(newly) < limit:
            t = queue.popleft()
            if t in self.filled or t in self.finish_tiles:
                continue
            self.filled.add(t)
            newly.append(t)
        return newly

    def _corridor_step(self):
        if not self.spine:
            return []

        # Keep finish approach open until late.
        guard = max(4, int(len(self.spine) * 0.12))
        hard_limit = max(0, len(self.spine) - guard)

        if self._corridor_index >= hard_limit:
            # Only allow final advance when all pockets are already filled.
            if len(self._pocket_filled) < len(self.pockets):
                return []
            hard_limit = len(self.spine)

        newly = []
        step_cap = max(1, SHRINK_CORRIDOR_STEP_TILES)
        while self._corridor_index < hard_limit and len(newly) < step_cap:
            t = self.spine[self._corridor_index]
            self._corridor_index += 1
            if t in self.finish_tiles or t in self.filled:
                continue
            self.filled.add(t)
            newly.append(t)
        return newly

    def update(self, dt):
        """Advance state machine; return newly filled tiles this update."""
        self.time += dt
        if self.time < SHRINK_START_SEC:
            return []

        if self.pause > 0:
            self.pause = max(0.0, self.pause - dt)
            return []

        if self._state == "waiting_start":
            self._state = "spawn_fill"

        if self._state == "spawn_fill":
            newly = self._fill_queue(self._spawn_fill_queue, max(1, SHRINK_CORRIDOR_STEP_TILES))
            if newly:
                self.frontier = set(newly)
                self.pause = SHRINK_STEP_PAUSE_SEC
                return newly
            self._state = "pocket_fill"

        if self._state == "pocket_fill":
            ranked = self._rank_pockets()
            if not ranked:
                self._state = "corridor_advance"
            else:
                newly = []
                for idx, _, _ in ranked[: max(1, SHRINK_POCKET_BATCH)]:
                    # Fill selected pockets as a region block (deep->entrance ordering).
                    queue = self._pocket_fill_queues[idx]
                    while queue:
                        t = queue.popleft()
                        if t in self.filled or t in self.finish_tiles:
                            continue
                        self.filled.add(t)
                        newly.append(t)
                    self._pocket_filled.add(idx)
                if newly:
                    self.frontier = set(newly)
                    self.pause = SHRINK_POCKET_PAUSE_SEC
                    self._state = "corridor_advance"
                    return newly
                self._state = "corridor_advance"

        if self._state == "corridor_advance":
            newly = self._corridor_step()
            if newly:
                self.frontier = set(newly)
                self.pause = SHRINK_STEP_PAUSE_SEC
                self._state = "pocket_fill"
                return newly
            # nothing left to advance
            self._state = "done"

        return []
