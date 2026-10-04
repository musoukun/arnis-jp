"""
写真1枚から建物を作る（仕様 JSON 方式）。img2threejs の進め方を建物用に小さくしたもの:
  仕様は JSON 1つ（部品の一覧）→ 段階ごとに組み立て → 毎段、写真と並べた比較シート → モデルが1つ決める。

  python sculpt.py sheet  <仕様.json> [段階]   … 比較シート out/sculpt/<名前>_<段階>.png
  python sculpt.py measure <仕様.json> u v <面 n|s|w|e|角 NW..>   … 写真の画素 → その点の位置（局所座標・地面からの段）
  python sculpt.py build  <仕様.json> ["メモ"]  … 施工（解体・控え・差分施工・看板は run.py と同じ仕組み）

段階（parts の "pass"）: blockout（形だけ）→ form（帯・塔・柵など）→ material（素材）→ detail（窓・入口・看板・室内）。
blockout と form の比較シートは白いクレイ（部品ごとに色分けして写真に重ねる）。material からは素材で描く。

座標の決まり（ワールドを作り直しても使えるように、建物の形からの相対で書く）:
  局所 x, z  … OSM の建物のセルの最小 x・最小 z を 0 とするセル番号（x 東、z 南）
  段 y       … 地面のブロック G を 0 として上へ 1, 2, ...（1 = 地面のすぐ上の段）
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402
from parcel import OsmGeometry, cells_in, outline  # noqa: E402
from photo_camera import Camera, solve  # noqa: E402

OUT = config.work("out", "sculpt")   # 作業フォルダの out/sculpt/
PASSES = ["blockout", "form", "material", "detail"]
STEP = {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}
FACING = {"n": "north", "s": "south", "w": "west", "e": "east"}
OPP = {"n": "south", "s": "north", "w": "east", "e": "west"}
# クレイの色（部品ごとに見分ける）
CLAY = ["white_concrete", "light_blue_concrete", "yellow_concrete", "lime_concrete", "pink_concrete",
        "orange_concrete", "cyan_concrete", "magenta_concrete", "light_gray_concrete"]
FONT = "C:/Windows/Fonts/BIZ-UDGothicB.ttc"


# ---------------- 仕様と建物の枠 ----------------

def load(path):
    path = Path(path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["_path"] = path
    return spec


def save(spec):
    data = {k: v for k, v in spec.items() if not k.startswith("_")}
    spec["_path"].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Frame:
    """建物の局所座標の枠。OSM の形、地面 G、局所 ↔ ワールドの変換。"""

    def __init__(self, spec, geo=None, G=None):
        # 仕様に "osm" があればそれ（作業を始めたフォルダからのパス）、無ければ設定の OSM データ
        self.geo = geo or OsmGeometry(config.path_of(spec["osm"]) if spec.get("osm") else None)
        self.poly = self.geo.polygon(spec["way"])
        self.bld = cells_in(self.poly)
        self.x0 = min(x for x, _ in self.bld)
        self.z0 = min(z for _, z in self.bld)
        self.wall = outline(self.bld)
        self.G = G if G is not None else spec.get("ground_y")
        if self.G is None:
            self.G = self._detect_ground()

    def _detect_ground(self):
        from collections import Counter
        from world_reader import load_area
        ring = {(x + dx, z + dz) for (x, z) in self.bld for dx in (-4, 4) for dz in (-4, 4)} - self.bld
        xs, zs = [c[0] for c in ring], [c[1] for c in ring]
        snap = load_area(min(xs), min(zs), max(xs), max(zs), y0=-64, y1=0)
        top = {}
        for (x, y, z) in snap.blocks:
            if (x, z) in ring and y > top.get((x, z), -999):
                top[(x, z)] = y
        return Counter(top.values()).most_common(1)[0][0]

    def world(self, lx, row, lz):
        return self.x0 + lx, self.G + row, self.z0 + lz

    def local(self, x, y, z):
        return x - self.x0, y - self.G, z - self.z0

    def corner(self, name):
        """角の名前（NW/NE/SW/SE）→ その角に一番近い OSM の頂点 (x, z)。"""
        sx = -1 if "W" in name else 1
        sz = -1 if "N" in name else 1
        return max(self.poly, key=lambda p: sx * p[0] + sz * p[1])

    def face_line(self, face):
        """面（n/s/w/e）→ その面の壁の線（OSM の頂点2つ）。その向きに一番外にある辺を選ぶ。"""
        dx, dz = STEP[face]
        n = len(self.poly)
        best, score = None, -1e9
        for i in range(n):
            a, b = self.poly[i], self.poly[(i + 1) % n]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length < 2:
                continue
            nx, nz = (b[1] - a[1]) / length, -(b[0] - a[0]) / length  # 辺の法線（どちら向きかは下で決める）
            align = abs(nx * dx + nz * dz)
            if align < 0.9:
                continue
            mid = ((a[0] + b[0]) / 2) * dx + ((a[1] + b[1]) / 2) * dz
            s = mid + length * 0.01
            if s > score:
                best, score = (a, b), s
        return best


# ---------------- 部品 → ブロック ----------------

def part_cells(part, fr, built):
    """部品の平面のセル（ワールド座標の (x, z) の集合）。"""
    shape = part["shape"]
    if shape in ("extrude", "roof"):
        return set(fr.bld)
    if shape == "ring":
        off = part.get("offset", 1)
        grown = {(x + dx, z + dz) for (x, z) in fr.bld for dx in range(-off, off + 1) for dz in range(-off, off + 1)}
        return grown - fr.bld
    if shape == "box":
        (ax, bx), (az, bz) = part["x"], part["z"]
        cells = {(fr.x0 + x, fr.z0 + z) for x in range(ax, bx + 1) for z in range(az, bz + 1)}
        return cells & fr.bld if part.get("clip", True) else cells
    if shape == "edge":
        faces = set(part["faces"])
        base = part_cells({"shape": "ring", "offset": 1}, fr, built) if part.get("on") == "ring" else None
        if base is not None:
            cells = {c for c, d in outline(base | fr.bld).items() if set(d) & faces}
            cells = {c for c in cells if c in base}
        else:
            cells = {c for c, d in fr.wall.items() if set(d) & faces}
        avoid = set().union(*(built.get(a, set()) for a in part.get("except", [])))
        near = {(x + dx, z + dz) for (x, z) in avoid for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
        return cells - near
    if shape == "panel":
        # 面の一部: face の壁のセルのうち、面に沿った局所座標 u（n/s は x、w/e は z）が範囲内のもの
        face = part["face"]
        a, b = part["u"]
        ux = face in ("n", "s")
        return {(x, z) for (x, z), d in fr.wall.items()
                if face in d and a <= ((x - fr.x0) if ux else (z - fr.z0)) <= b}
    raise ValueError(f"知らない形: {shape}")


def build_blocks(spec, fr, upto="detail", clay=None):
    """仕様 → {(x,y,z): 状態}、{部品id: セル集合}。upto の段階まで。clay=True なら部品ごとの色で描く。"""
    if clay is None:
        clay = PASSES.index(upto) < PASSES.index("material")
    mats = spec.get("materials", {})
    blocks, built, order = {}, {}, []
    for i, part in enumerate(spec["parts"]):
        if PASSES.index(part.get("pass", "blockout")) > PASSES.index(upto):
            continue
        cells = part_cells(part, fr, built)
        built[part["id"]] = cells
        order.append(part["id"])
        a, b = part["y"]
        mat = CLAY[(len(order) - 1) % len(CLAY) if part["id"] != "body" else 0] if clay else mats.get(part.get("material"), part.get("material", "white_concrete"))
        hollow = part.get("hollow", False)
        faces_of = outline(cells) if (part["shape"] == "edge" or hollow) else {}
        every = part.get("mullion_every")
        frame = mats.get(part.get("mullion"), part.get("mullion", "polished_blackstone"))
        for (x, z) in cells:
            if hollow and (x, z) not in faces_of:
                continue
            u = (x - fr.x0) if part.get("face") in ("n", "s") else (z - fr.z0)
            for row in range(a, b + 1):
                s = mat
                if not clay and every and u % every == 0:
                    s = frame
                if not clay and "trapdoor" in mat and (x, z) in faces_of:
                    out = [f for f in faces_of[(x, z)] if (x + STEP[f][0], z + STEP[f][1]) not in fr.bld]
                    f = out[0] if out else faces_of[(x, z)][0]
                    s = f"{mat}[facing={OPP[f]},half=bottom,open=true]"
                blocks[(x, fr.G + row, z)] = s
    return blocks, built, order


# ---------------- カメラ ----------------

def camera(spec, size):
    c = spec.get("camera", {})
    if "solved" in c:
        s = c["solved"]
        return Camera(s["pos"], s["yaw"], s["pitch"], s["focal"], size)
    raise SystemExit("camera.solved がありません（streetview_url か points から求める）")


def solve_camera(spec, fr, size):
    """camera.points（[画素, [局所x, 段 or 名前, 局所z]]）からカメラと名前付きの高さを求めて保存する。"""
    pts = []
    for (u, v), (lx, row, lz) in spec["camera"]["points"]:
        x, z = fr.x0 + lx, fr.z0 + lz
        y = row if isinstance(row, str) else fr.G + row
        pts.append(((u, v), (x, y, z)))
    g = spec["camera"]["guess"]
    guess = dict(g, x=fr.x0 + g["lx"], z=fr.z0 + g["lz"], eye_y=fr.G + g.get("eye_row", 3))
    for p in pts:
        if isinstance(p[1][1], str):
            guess.setdefault(p[1][1], fr.G + 5)
    cam, hs, err = solve(pts, size, None, guess)
    spec["camera"]["solved"] = {"pos": [round(float(v), 3) for v in cam.pos], "yaw": round(cam.yaw, 2),
                                "pitch": round(cam.pitch, 2), "focal": round(cam.focal, 2),
                                "vfov": round(cam.vfov, 2), "error_px": [round(float(e), 1) for e in err],
                                "heights_row": {k: round(v - fr.G, 2) for k, v in hs.items()}}
    save(spec)
    return cam


# ---------------- 比較シート ----------------

def sheet(spec, upto="blockout"):
    fr = Frame(spec)
    photo = Image.open(config.path_of(spec["photo"])).convert("RGB")
    if "solved" not in spec.get("camera", {}):
        solve_camera(spec, fr, photo.size)
    cam = camera(spec, photo.size)
    blocks, built, order = build_blocks(spec, fr, upto)
    from render import VoxelScene, render_view
    from world_reader import WorldSnapshot, load_area
    xs = [p[0] for p in blocks]; zs = [p[2] for p in blocks]
    w, h = photo.size
    # 1) クレイだけ（空の世界）を写真に重ねる
    only = WorldSnapshot({}, (min(xs) - 2, fr.G - 1, min(zs) - 2, max(xs) + 2, fr.G + 40, max(zs) + 2))
    img, mask = render_view(VoxelScene(only, blocks), tuple(cam.pos), cam.yaw, cam.pitch, w, h, cam.vfov, with_mask=True)
    over = Image.composite(Image.blend(photo, img, 0.55), photo, Image.fromarray((mask * 255).astype(np.uint8)))
    d = ImageDraw.Draw(over)
    # クレイの輪郭（マスクの境目）を線で
    edge = mask ^ np.roll(mask, 1, 0) | mask ^ np.roll(mask, 1, 1)
    ys, xs2 = np.nonzero(edge)
    for y, x in zip(ys[::2], xs2[::2]):
        d.point((int(x), int(y)), fill=(255, 0, 255))
    # 2) まわりの街も入れて、同じ視点で描く
    snap = load_area(min(xs) - 40, min(zs) - 40, max(xs) + 40, max(zs) + 40, y0=-64, y1=fr.G + 40)
    clear = {(x, y, z): "minecraft:air" for (x, z) in fr.bld | set().union(*built.values())
             for y in range(fr.G + 1, fr.G + 40)}
    clear.update(blocks)
    view = render_view(VoxelScene(snap, clear), tuple(cam.pos), cam.yaw, cam.pitch, w, h, cam.vfov)
    # 並べる
    font = ImageFont.truetype(FONT, 22)
    bar = 40
    out = Image.new("RGB", (w * 2, h + bar + 60), "white")
    dd = ImageDraw.Draw(out)
    dd.text((10, 8), f"写真＋クレイ（{upto}）", fill="black", font=font)
    dd.text((w + 10, 8), "同じ視点の描画", fill="black", font=font)
    out.paste(over, (0, bar))
    out.paste(view, (w, bar))
    if PASSES.index(upto) < PASSES.index("material"):
        legend = "  ".join(f"{pid}={CLAY[i % len(CLAY) if pid != 'body' else 0].replace('_concrete', '')}"
                           for i, pid in enumerate(order))
        dd.text((10, h + bar + 12), "部品の色: " + legend, fill="black", font=ImageFont.truetype(FONT, 16))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{spec['name']}_{upto}.png"
    out.save(path)
    print(cam)
    print("→", path)
    return path


# ---------------- 写真の画素 → 位置 ----------------

def measure(spec, u, v, where):
    """写真の画素が、面（n/s/w/e の壁の面）か角（NW 等の縦の線）の上にあるとして、局所座標と段を返す。"""
    fr = Frame(spec)
    photo = Image.open(config.path_of(spec["photo"]))
    cam = camera(spec, photo.size)
    if where in STEP:
        a, b = fr.face_line(where)
        p = cam.on_wall((u, v), a, b)
        lx, row, lz = fr.local(*p)
    else:
        cx, cz = fr.corner(where)
        row = cam.on_vertical((u, v), (cx, cz)) - fr.G
        lx, lz = cx - fr.x0, cz - fr.z0
    print(f"局所 x={lx:.1f} z={lz:.1f}  地面からの段 y={row:.2f}（その段の上端の高さ。ブロックの段なら切り捨て）")
    return lx, row, lz


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "sheet":
        sheet(load(a[1]), a[2] if len(a) > 2 else "blockout")
    elif a[0] == "measure":
        measure(load(a[1]), float(a[2]), float(a[3]), a[4])
    elif a[0] == "solve":
        s = load(a[1]); s.get("camera", {}).pop("solved", None)
        fr = Frame(s); solve_camera(s, fr, Image.open(config.path_of(s["photo"])).size); print(s["camera"]["solved"])
    else:
        print(__doc__)
