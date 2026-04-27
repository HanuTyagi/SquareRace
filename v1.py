import pygame
import pymunk
import random
import math
import collections

# --- CONFIGURATION ---
TILE_SIZE = 20
GRID_W, GRID_H = 32, 50
WIDTH, HEIGHT = GRID_W * TILE_SIZE, GRID_H * TILE_SIZE
FPS = 60

# --- ADJUSTED PHYSICS & VISUALS ---
CONSTANT_SPEED = 80   
SQUARE_SIZE = 20         
TRAIL_LENGTH = 15        

# Slate Aesthetic Colors
COLOR_WALL = (60, 65, 80)
COLOR_PATH = (25, 25, 30)
COLOR_CHECKER_1 = (220, 220, 220)
COLOR_CHECKER_2 = (150, 150, 150)
COLOR_FINISH_1 = (255, 150, 50)
COLOR_FINISH_2 = (50, 50, 50)
SQUARE_COLORS = [(255, 50, 50), (50, 50, 255), (50, 255, 50), (255, 255, 50)]

# --- MAP GENERATION LOGIC ---
def draw_checkered_rect(surface, rect, c1, c2, checks=2):
    cw = rect.width // checks
    ch = rect.height // checks
    for row in range(checks):
        for col in range(checks):
            color = c1 if (row + col) % 2 == 0 else c2
            check_rect = pygame.Rect(rect.x + col * cw, rect.y + row * ch, cw, ch)
            pygame.draw.rect(surface, color, check_rect)

def get_shortest_path(grid, start_x, start_y, goal_x, goal_y):
    queue = collections.deque([[(start_x, start_y)]])
    seen = set([(start_x, start_y)])
    while queue:
        path = queue.popleft()
        x, y = path[-1]
        if x == goal_x and y == goal_y:
            return path
        for dx, dy in [(0,1), (1,0), (0,-1), (-1,0)]:
            nx, ny = x + dx, y + dy
            if 0 < nx < len(grid[0]) and 0 < ny < len(grid) and grid[ny][nx] in [0, 3]:
                if (nx, ny) not in seen:
                    queue.append(path + [(nx, ny)])
                    seen.add((nx, ny))
    return []

def generate_slate_arena(w, h):
    while True:
        grid = [[0 for _ in range(w)] for _ in range(h)]
        for x in range(w): grid[0][x] = 1; grid[h-1][x] = 1
        for y in range(h): grid[y][0] = 1; grid[y][w-1] = 1

        # 1. EXACTLY 9 EDGE-ANCHORED OBSTACLES
        num_edge_blocks = 9
        for _ in range(num_edge_blocks):
            side = random.choice(['top', 'bottom', 'left', 'right'])
            bw, bh = random.randint(2, 6), random.randint(2, 6)
            if side == 'top': bx, by = random.randint(1, w - bw - 1), 1
            elif side == 'bottom': bx, by = random.randint(1, w - bw - 1), h - bh - 1
            elif side == 'left': bx, by = 1, random.randint(1, h - bh - 1)
            else: bx, by = w - bw - 1, random.randint(1, h - bh - 1)
            
            for y in range(by, by + bh):
                for x in range(bx, bx + bw):
                    if 0 < x < w-1 and 0 < y < h-1:
                        grid[y][x] = 1

        # 2. EXACTLY 4 CENTRAL OBSTACLES
        num_blocks = 4
        for _ in range(num_blocks):
            bw, bh = random.randint(2, 5), random.randint(2, 5)
            bx, by = random.randint(1, w - bw - 1), random.randint(1, h - bh - 4) 
            for y in range(by, by + bh):
                for x in range(bx, bx + bw):
                    if 0 < x < w-1 and 0 < y < h-1:
                        grid[y][x] = 1

        # 3. RANDOM OMNIDIRECTIONAL SPAWN AREA
        # Pick random coordinates and carve a guaranteed safe 6x3 open buffer around it
        spawn_x = random.randint(2, w - 6)
        spawn_y = random.randint(2, h - 3)
        
        for y in range(spawn_y - 1, spawn_y + 2):
            for x in range(spawn_x - 1, spawn_x + 5):
                if 0 < x < w-1 and 0 < y < h-1:
                    grid[y][x] = 0

        # 4. FIND WALL-ANCHORED TILES FOR FINISH LINE
        anchored_tiles = []
        for y in range(1, h-1):
            for x in range(1, w-1):
                if grid[y][x] == 0:
                    # Check if it touches at least 1 wall (Edge or Center block)
                    walls = sum(1 for dx, dy in [(0,1), (1,0), (0,-1), (-1,0)] if grid[y+dy][x+dx] == 1)
                    if walls >= 1: 
                        anchored_tiles.append((x, y))

        if not anchored_tiles: 
            continue

        valid_finish_starts = [c for c in anchored_tiles if math.hypot(c[0] - spawn_x, c[1] - spawn_y) >= 12]
        if not valid_finish_starts: 
            valid_finish_starts = anchored_tiles 

        fx, fy = random.choice(valid_finish_starts)
        
        # 5. FIXED OMNIDIRECTIONAL FINISH LINE LOGIC (2-4 blocks)
        finish_len = random.randint(2, 4)
        valid_placements = []
        
        # Check Right (+dx)
        if all(0 < fx+dx < w-1 and grid[fy][fx+dx] == 0 for dx in range(finish_len)):
            valid_placements.append([(fx+dx, fy) for dx in range(finish_len)])
        # Check Left (-dx)
        if all(0 < fx-dx < w-1 and grid[fy][fx-dx] == 0 for dx in range(finish_len)):
            valid_placements.append([(fx-dx, fy) for dx in range(finish_len)])
        # Check Down (+dy)
        if all(0 < fy+dy < h-1 and grid[fy+dy][fx] == 0 for dy in range(finish_len)):
            valid_placements.append([(fx, fy+dy) for dy in range(finish_len)])
        # Check Up (-dy)
        if all(0 < fy-dy < h-1 and grid[fy-dy][fx] == 0 for dy in range(finish_len)):
            valid_placements.append([(fx, fy-dy) for dy in range(finish_len)])

        # If it can't place a full block in ANY direction, discard map
        if not valid_placements:
            continue

        finish_tiles_placed = random.choice(valid_placements)
        for px, py in finish_tiles_placed:
            grid[py][px] = 3

        # 6. STRICT MULTI-PATH VALIDATION
        # Ensure path exists from the new random spawn to ALL finish blocks
        all_reachable = True
        for target_x, target_y in finish_tiles_placed:
            if not get_shortest_path(grid, spawn_x + 1, spawn_y, target_x, target_y):
                all_reachable = False
                break
                
        if not all_reachable:
            continue

        # 7. PERCENTAGE BASED ITEM SPAWNING AROUND PATH
        shortest_path = get_shortest_path(grid, spawn_x + 1, spawn_y, finish_tiles_placed[0][0], finish_tiles_placed[0][1])
        path_set = set(shortest_path)
        buffer_zone = []
        buffer_radius = random.randint(5, 9) 
        
        for y in range(1, h-1):
            for x in range(1, w-1):
                if grid[y][x] == 0 and (x, y) not in path_set:
                    for px, py in shortest_path:
                        if abs(x - px) + abs(y - py) <= buffer_radius:
                            buffer_zone.append((x, y))
                            break
                            
        random.shuffle(buffer_zone)
        
        # 40% (0), 30% (1), 20% (2), 10% (3)
        rand_val = random.random()
        if rand_val < 0.40: num_items = 0
        elif rand_val < 0.70: num_items = 1
        elif rand_val < 0.90: num_items = 2
        else: num_items = 3

        for i in range(min(num_items, len(buffer_zone))):
            ix, iy = buffer_zone[i]
            grid[iy][ix] = 2

        # Return the exact pixel center of the 4x1 open area
        spawn_pixel_center = ((spawn_x + 1.5) * TILE_SIZE, (spawn_y + 0.5) * TILE_SIZE)
        return grid, spawn_pixel_center

# --- MAIN SIMULATION ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    trail_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.display.set_caption("Auto Race - Final Arena Logic")
    clock = pygame.time.Clock()

    space = pymunk.Space()
    space.gravity = (0, 0)

    grid, spawn_center = generate_slate_arena(GRID_W, GRID_H)

    finish_rects = []
    item_rects = []
    
    for y in range(GRID_H):
        for x in range(GRID_W):
            tile = grid[y][x]
            rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
            if tile == 1:
                body = pymunk.Body(body_type=pymunk.Body.STATIC)
                body.position = (x * TILE_SIZE + TILE_SIZE/2, y * TILE_SIZE + TILE_SIZE/2)
                shape = pymunk.Poly.create_box(body, (TILE_SIZE, TILE_SIZE))
                shape.elasticity = 1.0 
                shape.friction = 0.0
                space.add(body, shape)
            elif tile == 3:
                finish_rects.append(rect)
            elif tile == 2:
                item_rects.append(rect)

    racers = []
    base_angle = random.uniform(0, math.pi * 2)
    
    for i in range(4):
        mass = 1
        size = (SQUARE_SIZE, SQUARE_SIZE) 
        moment = pymunk.moment_for_box(mass, size)
        body = pymunk.Body(mass, moment)
        
        offset_x = (i - 1.5) * (SQUARE_SIZE + 2) 
        body.position = (spawn_center[0] + offset_x, spawn_center[1])
        
        shape = pymunk.Poly.create_box(body, size)
        shape.elasticity = 1.0
        shape.friction = 0.0
        shape.color = SQUARE_COLORS[i]
        shape.name = ["Red", "Blue", "Green", "Yellow"][i]
        space.add(body, shape)
        
        angle = base_angle + math.radians(i * 25)
        body.velocity = (math.cos(angle) * CONSTANT_SPEED, math.sin(angle) * CONSTANT_SPEED)
        
        racers.append({
            "body": body, "shape": shape, "color": shape.color, 
            "name": shape.name, "history": []
        })

    running = True
    winner = None

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        for racer in racers:
            v = racer["body"].velocity
            if v.length > 0:
                racer["body"].velocity = v.normalized() * CONSTANT_SPEED
            
            pos = racer["body"].position
            racer["history"].append((pos.x, pos.y))
            if len(racer["history"]) > TRAIL_LENGTH:
                racer["history"].pop(0)

        space.step(1 / FPS)
        screen.fill(COLOR_PATH)

        for y in range(GRID_H):
            for x in range(GRID_W):
                tile = grid[y][x]
                rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                if tile == 1:
                    pygame.draw.rect(screen, COLOR_WALL, rect)
                elif tile == 2:
                    draw_checkered_rect(screen, rect, COLOR_CHECKER_1, COLOR_CHECKER_2, 2)
                elif tile == 3:
                    draw_checkered_rect(screen, rect, COLOR_FINISH_1, COLOR_FINISH_2, 3)

        pygame.draw.circle(screen, (80, 80, 90), (int(spawn_center[0]), int(spawn_center[1])), 10, 2)
        trail_overlay.fill((0, 0, 0, 0)) 
        
        for racer in racers:
            color = racer["color"]
            hist = racer["history"]
            for i, (hx, hy) in enumerate(hist):
                alpha = int(180 * (i / max(1, len(hist)))) 
                t_size = SQUARE_SIZE * (0.6 + 0.4 * (i / max(1, len(hist))))
                offset = t_size / 2
                trail_rect = pygame.Rect(hx - offset, hy - offset, t_size, t_size)
                pygame.draw.rect(trail_overlay, (*color, alpha), trail_rect)

        screen.blit(trail_overlay, (0, 0))

        for racer in racers:
            pos = racer["body"].position
            draw_pos = (int(pos.x - SQUARE_SIZE/2), int(pos.y - SQUARE_SIZE/2))
            pygame.draw.rect(screen, racer["color"], (*draw_pos, SQUARE_SIZE, SQUARE_SIZE))

            for f_rect in finish_rects:
                if f_rect.collidepoint(pos.x, pos.y) and winner is None:
                    winner = racer["name"]
                    print(f"[{winner}] has reached the Finish Line!")
            
            for i_rect in item_rects[:]:
                if i_rect.collidepoint(pos.x, pos.y):
                    print(f"[{racer['name']}] picked up an item!")
                    item_rects.remove(i_rect)
                    grid[i_rect.y // TILE_SIZE][i_rect.x // TILE_SIZE] = 0

        if winner:
            font = pygame.font.SysFont(None, 48)
            text = font.render(f"{winner} Wins!", True, (255, 255, 255))
            screen.blit(text, (WIDTH//2 - 100, HEIGHT//2))
            pygame.display.flip()
            pygame.time.wait(3000)
            running = False

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

if __name__ == "__main__":
    main()
