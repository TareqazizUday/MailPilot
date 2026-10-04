"""Remove outer white sticker rims using distance-to-content vs distance-to-transparent."""
from __future__ import annotations

import collections
import os
from PIL import Image

BASE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static",
    "img",
    "hero-agents",
)


def near_white(r: int, g: int, b: int, a: int, thresh: int = 230) -> bool:
    return a > 18 and r >= thresh and g >= thresh and b >= thresh


def bfs_dist(w: int, h: int, seeds: list[tuple[int, int]], can_enter) -> list[list[int]]:
    dist = [[10**9] * w for _ in range(h)]
    q: collections.deque[tuple[int, int]] = collections.deque()
    for x, y in seeds:
        dist[y][x] = 0
        q.append((x, y))
    while q:
        x, y = q.popleft()
        nd = dist[y][x] + 1
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and dist[ny][nx] > nd and can_enter(nx, ny):
                dist[ny][nx] = nd
                q.append((nx, ny))
    return dist


def fix_image(path: str) -> None:
    bak = path.replace(".png", ".bak.png")
    src = bak if os.path.exists(bak) else path
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    px = im.load()

    trans_seeds = []
    content_seeds = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a <= 18:
                trans_seeds.append((x, y))
            elif not near_white(r, g, b, a):
                content_seeds.append((x, y))

    # Distances travel through everything (so we measure geometry of the canvas)
    always = lambda _x, _y: True
    d_trans = bfs_dist(w, h, trans_seeds, always)
    d_content = bfs_dist(w, h, content_seeds, always)

    # Bias: prefer removing whites that are closer to outside than to content
    bias = 18
    removed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if not near_white(r, g, b, a):
                continue
            if d_trans[y][x] <= d_content[y][x] + bias:
                px[x, y] = (r, g, b, 0)
                removed += 1

    # Second pass: clear any remaining near-white fringe still touching transparency
    for _ in range(3):
        kill: list[tuple[int, int]] = []
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if not near_white(r, g, b, a, thresh=220):
                    continue
                # keep if tightly hugged by non-white content
                near_c = 0
                near_t = 0
                for nx, ny in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                    (x - 1, y - 1),
                    (x + 1, y - 1),
                    (x - 1, y + 1),
                    (x + 1, y + 1),
                ):
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    rr, gg, bb, aa = px[nx, ny]
                    if aa <= 18:
                        near_t += 1
                    elif not near_white(rr, gg, bb, aa, thresh=220):
                        near_c += 1
                if near_t > 0 and near_c == 0:
                    kill.append((x, y))
                elif near_t >= 2 and near_c <= 1:
                    kill.append((x, y))
        for x, y in kill:
            r, g, b, _a = px[x, y]
            px[x, y] = (r, g, b, 0)
            removed += 1

    bbox = im.getbbox()
    if bbox:
        l, t, r, b = bbox
        pad = 4
        im = im.crop((max(0, l - pad), max(0, t - pad), min(w, r + pad), min(h, b + pad)))

    im.save(path, optimize=True)
    data = list(im.getdata())
    nw = sum(1 for r, g, b, a in data if a > 200 and r > 240 and g > 240 and b > 240)
    print(f"{os.path.basename(path)}: removed={removed} size={im.size} near_white={nw}")


def main() -> None:
    for name in ("mp-agent-01.png", "mp-agent-02.png", "mp-agent-03.png"):
        fix_image(os.path.join(BASE, name))


if __name__ == "__main__":
    main()
