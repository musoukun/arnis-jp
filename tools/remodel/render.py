"""
ワールドのブロックを画像にする（検証用）。

- render_top(): 真上からの地図
- render_view(): プレイヤー視点の透視投影（numpy でまとめてレイを飛ばす）

実物のテクスチャ（16x16）を貼り、面の向きで明るさを変える（Minecraft と同じ係数）。
写真と同じ位置・向きから描いて見比べるのが目的なので、光や影の再現はしない。
"""

import math

import numpy as np
from PIL import Image

from block_colors import _texture_for, _tex_names, block_rgb, texture_rgba

# 描画しない（ほぼ見えない）ブロック
_SKIP_WORDS = ("torch", "sign", "banner", "button", "lever", "rail", "redstone_wire",
               "tripwire", "structure_void", "barrier", "light[", "cave_air")
_PLANTS = ("short_grass", "tall_grass", "fern", "dandelion", "poppy", "orchid", "allium",
           "azure_bluet", "tulip", "oxeye", "cornflower", "lily_of", "sapling", "dead_bush",
           "sweet_berry", "flower", "rose_bush", "peony", "lilac", "sunflower")

FULL = (0, 0, 0, 1, 1, 1)
EMPTY = (0, 0, 0, 0, 0, 0)
_FACE_SHADE = np.array([0.6, 1.0, 0.8, 0.6, 0.5, 0.8], dtype=np.float32)  # +x,+y,+z,-x,-y,-z


def _props(state: str) -> dict:
    if "[" not in state:
        return {}
    inner = state[state.index("[") + 1:-1]
    return dict(kv.split("=") for kv in inner.split(","))


def block_boxes(state: str):
    """状態文字列 → ボクセル内の箱 2 つ（局所座標 0..1）。描かないなら None。"""
    name = state.replace("minecraft:", "").split("[")[0]
    p = _props(state)
    if any(w in state for w in _SKIP_WORDS) or name in ("air", "void_air"):
        return None
    if any(w in name for w in _PLANTS):
        return None
    if name.endswith("_slab"):
        t = p.get("type", "bottom")
        return {"bottom": (0, 0, 0, 1, .5, 1), "top": (0, .5, 0, 1, 1, 1)}.get(t, FULL), EMPTY
    if name.endswith("_stairs"):
        f, half = p.get("facing", "north"), p.get("half", "bottom")
        main = (0, 0, 0, 1, .5, 1) if half == "bottom" else (0, .5, 0, 1, 1, 1)
        ylo, yhi = (.5, 1) if half == "bottom" else (0, .5)
        step = {"east": (.5, ylo, 0, 1, yhi, 1), "west": (0, ylo, 0, .5, yhi, 1),
                "south": (0, ylo, .5, 1, yhi, 1), "north": (0, ylo, 0, 1, yhi, .5)}[f]
        return main, step
    if name.endswith("_wall") or (name.endswith("_fence") and "gate" not in name):
        return (.25, 0, .25, .75, 1, .75), EMPTY
    if name.endswith("_carpet"):
        return (0, 0, 0, 1, 1 / 16, 1), EMPTY
    thin = {"north": (0, 0, 13 / 16, 1, 1, 1), "south": (0, 0, 0, 1, 1, 3 / 16),
            "west": (13 / 16, 0, 0, 1, 1, 1), "east": (0, 0, 0, 3 / 16, 1, 1)}
    if name.endswith("_trapdoor"):
        if p.get("open") == "true":
            return thin[p.get("facing", "north")], EMPTY
        return ((0, 13 / 16, 0, 1, 1, 1) if p.get("half") == "top" else (0, 0, 0, 1, 3 / 16, 1)), EMPTY
    if name.endswith("_door"):
        return thin[p.get("facing", "north")], EMPTY
    if name in ("lantern", "flower_pot") or name.startswith("potted_"):
        return (.3, 0, .3, .7, .6, .7), EMPTY
    return FULL, EMPTY


def _textures(state: str):
    """(側面テクスチャ, 上面テクスチャ) を 16x16x4 で返す。"""
    name = state.replace("minecraft:", "").split("[")[0]
    names = _tex_names()
    side = _texture_for(name)
    if name == "grass_block":
        side, top = "grass_block_side", "grass_block_top"
    else:
        base = side.removesuffix("_side").removesuffix("_top") if side else None
        top = f"{base}_top" if base and f"{base}_top" in names else side
        if base and f"{base}_side" in names:
            side = f"{base}_side"
    if side is None:
        rgb = block_rgb(name) or (255, 0, 255)  # 不明はマゼンタで目立たせる
        t = np.ones((16, 16, 4), dtype=np.float32)
        t[..., :3] = np.array(rgb, dtype=np.float32) / 255
        return t, t

    def sixteen(tex):
        a = texture_rgba(tex)
        if a.shape[0] != 16:
            a = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((16, 16), Image.NEAREST),
                           dtype=np.float32) / 255
        return a
    return sixteen(side), sixteen(top)


class VoxelScene:
    """WorldSnapshot（＋上書きブロック）を、レイを飛ばせる密な配列にしたもの。"""

    def __init__(self, snapshot, overrides: dict | None = None):
        x0, y0, z0, x1, y1, z1 = snapshot.bounds
        self.origin = np.array([x0, y0, z0])
        self.shape = (x1 - x0 + 1, y1 - y0 + 1, z1 - z0 + 1)
        blocks = dict(snapshot.blocks)
        if overrides:
            blocks.update(overrides)
        states = ["minecraft:air"]
        index = {"minecraft:air": 0}
        self.grid = np.zeros(self.shape, dtype=np.int32)
        for (x, y, z), s in blocks.items():
            if s not in index:
                index[s] = len(states)
                states.append(s)
            gx, gy, gz = x - x0, y - y0, z - z0
            if 0 <= gx < self.shape[0] and 0 <= gy < self.shape[1] and 0 <= gz < self.shape[2]:
                self.grid[gx, gy, gz] = index[s]
        n = len(states)
        self.states = states
        self.box = np.zeros((n, 2, 6), dtype=np.float32)
        self.drawn = np.zeros(n, dtype=bool)
        self.tex_side = np.zeros((n, 16, 16, 4), dtype=np.float32)
        self.tex_top = np.zeros((n, 16, 16, 4), dtype=np.float32)
        for i, s in enumerate(states[1:], start=1):
            boxes = block_boxes(s)
            if boxes is None:
                continue
            self.drawn[i] = True
            self.box[i] = np.array(boxes, dtype=np.float32)
            self.tex_side[i], self.tex_top[i] = _textures(s)
        self.grid[~self.drawn[self.grid]] = 0


def _sky(dirs):
    t = np.clip(dirs[:, 1] * 2 + 0.3, 0, 1)[:, None]
    return (1 - t) * np.array([0.78, 0.86, 0.95]) + t * np.array([0.45, 0.65, 0.92])


def render_view(scene: VoxelScene, pos, yaw, pitch, width=854, height=480, vfov=70.0,
                max_steps=400) -> Image.Image:
    """Minecraft の F3 表示と同じ yaw/pitch（度）で、pos（目の位置）から見た絵を描く。"""
    yr, pr = math.radians(yaw), math.radians(pitch)
    f = np.array([-math.sin(yr) * math.cos(pr), -math.sin(pr), math.cos(yr) * math.cos(pr)])
    r = np.cross(f, [0, 1, 0]); r /= np.linalg.norm(r)
    u = np.cross(r, f)
    th = math.tan(math.radians(vfov) / 2)
    tw = th * width / height
    jj, ii = np.meshgrid(np.arange(width), np.arange(height))
    nx = ((jj + 0.5) / width * 2 - 1) * tw
    ny = (1 - (ii + 0.5) / height * 2) * th
    dirs = f + nx[..., None] * r + ny[..., None] * u
    dirs = (dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)).reshape(-1, 3)

    o = np.asarray(pos, dtype=np.float64) - scene.origin  # グリッド座標
    n = dirs.shape[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / dirs
    step = np.sign(dirs).astype(np.int64)
    vox = np.floor(np.broadcast_to(o, (n, 3))).astype(np.int64)
    tdelta = np.abs(inv)
    tmax = np.where(step > 0, (vox + 1 - o) * inv, np.where(step < 0, (vox - o) * inv, np.inf))

    color = np.zeros((n, 3))
    trans = np.ones(n)
    active = np.arange(n)
    shape = np.array(scene.shape)
    for _ in range(max_steps):
        if active.size == 0:
            break
        v = vox[active]
        inside = np.all((v >= 0) & (v < shape), axis=1)
        ids = np.zeros(active.size, dtype=np.int32)
        ids[inside] = scene.grid[v[inside, 0], v[inside, 1], v[inside, 2]]
        cand = np.nonzero(ids > 0)[0]
        if cand.size:
            a = active[cand]
            best_t = np.full(cand.size, np.inf)
            best_face = np.zeros(cand.size, dtype=np.int64)
            for k in range(2):
                b = scene.box[ids[cand], k]
                lo = v[cand] + b[:, :3]
                hi = v[cand] + b[:, 3:]
                valid = np.all(b[:, 3:] > b[:, :3], axis=1)
                with np.errstate(invalid="ignore"):
                    t1 = (lo - o) * inv[a]
                    t2 = (hi - o) * inv[a]
                tn = np.nan_to_num(np.minimum(t1, t2), nan=-np.inf)
                tf = np.nan_to_num(np.maximum(t1, t2), nan=np.inf)
                tnear = tn.max(axis=1)
                tfar = tf.min(axis=1)
                axis = tn.argmax(axis=1)
                hit = valid & (tnear <= tfar) & (tfar > 0) & (tnear < best_t)
                best_t = np.where(hit, tnear, best_t)
                face = axis + np.where(dirs[a, axis] > 0, 3, 0)  # 法線は進行方向の逆
                best_face = np.where(hit, face, best_face)
            got = np.isfinite(best_t)
            if got.any():
                g = cand[got]
                ag = active[g]
                t = np.maximum(best_t[got], 0)
                p = o + dirs[ag] * t[:, None] - v[g]  # ボクセル内の位置
                fc = best_face[got]
                ax = fc % 3
                uu = np.where(ax == 0, p[:, 2], p[:, 0])
                vv = np.where(ax == 1, p[:, 2], 1 - p[:, 1])
                tx = np.clip((uu * 16).astype(int), 0, 15)
                ty = np.clip((vv * 16).astype(int), 0, 15)
                bid = ids[g]
                texel = np.where((ax == 1)[:, None], scene.tex_top[bid, ty, tx], scene.tex_side[bid, ty, tx])
                alpha = texel[:, 3]
                shade = _FACE_SHADE[fc]
                fog = np.exp(-t / 260.0)[:, None]
                c = texel[:, :3] * shade[:, None] * fog + _sky(dirs[ag]) * (1 - fog)
                w = trans[ag] * np.where(alpha > 0.1, np.maximum(alpha, 0.35), 0)
                color[ag] += w[:, None] * c
                trans[ag] *= 1 - np.where(alpha > 0.1, np.maximum(alpha, 0.35), 0)
        # 進める
        keep = trans[active] > 0.02
        out_far = np.any(((vox[active] < -1) & (step[active] < 0)) | ((vox[active] > shape) & (step[active] > 0)), axis=1)
        keep &= ~out_far
        active = active[keep]
        if active.size == 0:
            break
        tm = tmax[active]
        axis = tm.argmin(axis=1)
        rows = np.arange(active.size)
        vox[active, axis] += step[active, axis]
        tmax[active, axis] += tdelta[active, axis]
    color += trans[:, None] * _sky(dirs)
    img = (np.clip(color, 0, 1) * 255).astype(np.uint8).reshape(height, width, 3)
    return Image.fromarray(img)


def render_top(scene: VoxelScene, px=6, marks=()) -> Image.Image:
    """真上から見た地図。marks=[(x,z,(r,g,b)),...] で印を付ける。"""
    sx, sy, sz = scene.shape
    occupied = scene.grid > 0
    top = np.where(occupied.any(axis=1), sy - 1 - np.argmax(occupied[:, ::-1, :], axis=1), 0)
    ids = np.take_along_axis(scene.grid, top[:, None, :], axis=1)[:, 0, :]
    rgb = scene.tex_top[ids].mean(axis=(2, 3))[..., :3]
    h = (top - top.min()) / max(1, top.max() - top.min())
    rgb = rgb * (0.7 + 0.5 * h[..., None])
    img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8).transpose(1, 0, 2)  # [z, x]
    big = Image.fromarray(img).resize((sx * px, sz * px), Image.NEAREST)
    arr = np.asarray(big).copy()
    for x, z, col in marks:
        gx, gz = int(x - scene.origin[0]), int(z - scene.origin[2])
        arr[gz * px:(gz + 1) * px, gx * px:(gx + 1) * px] = col
    return Image.fromarray(arr)
