"""
看板などを「地図アート」（額縁に入れた地図 = 1ブロックに128x128ドット）で描く。

ブロックでは表せない 1m 未満の文字や絵を、実物大のまま読めるように置くための部品。
- パレットはスキルの assets/map_palette.json（Minecraft の地図の色、62色 x 明るさ4段）
- 地図データは world/data/ に map_<id>.dat と <id>.dat の両方で書く（arnis 本体と同じ）
- サーバーは一度読んだ地図をキャッシュするので、描き直すときは新しい id を使う
"""

import json
from pathlib import Path

import nbtlib
import numpy as np
from nbtlib.tag import Byte, ByteArray, Compound, Int, List, String
from PIL import Image, ImageDraw, ImageFont

import config
from block_colors import rgb_to_lab

FONT_BOLD = "C:/Windows/Fonts/BIZ-UDGothicB.ttc"
SIZE = 128


def _palette_source():
    """(base_colors, shade_multipliers)。"""
    p = json.loads((config.ASSETS / "map_palette.json").read_text(encoding="utf-8"))
    return [tuple(c) for c in p["base_colors"]], p["shade_multipliers"]


def _palette():
    colors, shades = _palette_source()
    ids, rgbs = [], []
    for b, (r, g, bl) in enumerate(colors):
        if b == 0:
            continue  # 0 は透明
        for s, m in enumerate(shades):
            ids.append(b * 4 + s)
            rgbs.append((r * m // 255, g * m // 255, bl * m // 255))
    return np.array(ids), rgb_to_lab(np.array(rgbs, dtype=np.float64))


_IDS, _LAB = _palette()


def quantize(img: Image.Image) -> bytes:
    """128x128 RGBA → 地図の色 id 列（透明は 0）。"""
    a = np.asarray(img.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS), dtype=np.float64)
    lab = rgb_to_lab(a[..., :3].reshape(-1, 3))
    d = ((lab[:, None, :] - _LAB[None, :, :]) ** 2).sum(-1)
    ids = _IDS[d.argmin(1)]
    ids[a[..., 3].reshape(-1) < 128] = 0
    return bytes(int(v) & 0xFF for v in ids)


def write_map(map_id: int, img: Image.Image, world: Path = None):
    world = world or config.world()
    data_version = int(nbtlib.load(world / "level.dat")["Data"]["DataVersion"])
    colors = quantize(img)
    root = nbtlib.File({
        "DataVersion": Int(data_version),
        "data": Compound({
            "scale": Byte(0), "dimension": String("minecraft:overworld"),
            "trackingPosition": Byte(0), "unlimitedTracking": Byte(0), "locked": Byte(1),
            "xCenter": Int(0), "zCenter": Int(0),
            "colors": ByteArray([b - 256 if b > 127 else b for b in colors]),
            "banners": List[Compound]([]), "frames": List[Compound]([]),
        }),
    }, gzipped=True)
    for name in (f"map_{map_id}.dat", f"{map_id}.dat"):
        root.save(world / "data" / name)


def split_tiles(img: Image.Image, cols: int, rows: int):
    """cols x rows ブロック分の画像を、左上から 1 ブロック（128px）ずつに切る。"""
    img = img.resize((cols * SIZE, rows * SIZE), Image.LANCZOS)
    return [[img.crop((c * SIZE, r * SIZE, (c + 1) * SIZE, (r + 1) * SIZE)) for c in range(cols)]
            for r in range(rows)]


def text_image(parts, cols: int, rows: int, bg=(0, 0, 0, 0), outline=None, align="center"):
    """parts = [(文字列, 色, 高さの割合)] を横に並べた cols x rows ブロックの画像。"""
    W, H = cols * SIZE, rows * SIZE
    img = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(img)
    gap = int(H * 0.08)
    k = 1.0  # 横幅に収まるまで全体を縮める
    while True:
        fonts = [ImageFont.truetype(FONT_BOLD, max(8, int(H * frac * k))) for _, _, frac in parts]
        widths = [d.textbbox((0, 0), t, font=f)[2] for (t, _, _), f in zip(parts, fonts)]
        total = sum(widths) + gap * (len(parts) - 1)
        if total <= W * 0.94 or k < 0.2:
            break
        k *= 0.95
    x = (W - total) // 2 if align == "center" else gap
    for (t, color, frac), f, w in zip(parts, fonts, widths):
        bbox = d.textbbox((0, 0), t, font=f)
        y = (H - (bbox[3] - bbox[1])) // 2 - bbox[1]
        if outline:
            for dx in (-3, 0, 3):
                for dy in (-3, 0, 3):
                    d.text((x + dx, y + dy), t, font=f, fill=outline)
        d.text((x, y), t, font=f, fill=color)
        x += w + gap
    return img


def vertical_text_image(text: str, cols: int, rows: int, fg, bg, top_band=None):
    """縦書きの看板（1列）。top_band=(高さの割合, 色) で上端に帯を付ける。"""
    W, H = cols * SIZE, rows * SIZE
    img = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(img)
    y0 = 0
    if top_band:
        frac, color = top_band
        y0 = int(H * frac)
        d.rectangle((0, 0, W, y0), fill=color)
    n = len(text)
    cell = (H - y0) // (n + 1)
    f = ImageFont.truetype(FONT_BOLD, int(min(cell, W) * 0.85))
    for i, ch in enumerate(text):
        bb = d.textbbox((0, 0), ch, font=f)
        d.text(((W - (bb[2] - bb[0])) // 2 - bb[0], y0 + cell // 2 + i * cell - bb[1]), ch, font=f, fill=fg)
    return img


def _palette_rgb():
    colors, shades = _palette_source()
    return {b * 4 + s: (r * m // 255, g * m // 255, bl * m // 255)
            for b, (r, g, bl) in enumerate(colors) for s, m in enumerate(shades)}


def preview(img: Image.Image, cols: int, rows: int, bg=(70, 60, 55)) -> Image.Image:
    """地図の色に減色した後の見え方（透明部分は bg）。確認用。"""
    pal = _palette_rgb()
    out = Image.new("RGB", (cols * SIZE, rows * SIZE), bg)
    for r, row in enumerate(split_tiles(img, cols, rows)):
        for c, tile in enumerate(row):
            ids = quantize(tile)
            px = np.array([pal[i] if i else bg for i in ids], dtype=np.uint8).reshape(SIZE, SIZE, 3)
            out.paste(Image.fromarray(px), (c * SIZE, r * SIZE))
    return out
