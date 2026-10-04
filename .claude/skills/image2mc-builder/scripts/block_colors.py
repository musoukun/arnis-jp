"""
クライアント jar のテクスチャから、ブロックごとの平均色を求める。

- 描画（render.py）の色付け
- 写真の色 → 最も近いブロックの選択（Lab 色空間）
の両方で使う。
"""

import io
import os
import re
import zipfile
from functools import lru_cache

import numpy as np
from PIL import Image

import config

TEX = "assets/minecraft/textures/block/"

# 形状系サフィックス → 元素材（stairs/slab などは素材テクスチャを使う）
_SHAPE_SUFFIX = re.compile(r"_(stairs|slab|wall|fence_gate|fence|pressure_plate|button)$")
# 名前とテクスチャ名が違う代表的なもの
_ALIAS = {
    "bricks": "bricks", "brick": "bricks", "stone_brick": "stone_bricks",
    "nether_brick": "nether_bricks", "red_nether_brick": "red_nether_bricks",
    "mud_brick": "mud_bricks", "end_stone_brick": "end_stone_bricks",
    "quartz": "quartz_block_side", "smooth_quartz": "quartz_block_bottom",
    "quartz_block": "quartz_block_side", "smooth_sandstone": "sandstone_top",
    "smooth_red_sandstone": "red_sandstone_top", "smooth_stone": "smooth_stone",
    "snow_block": "snow", "grass_block": "grass_block_top", "dirt_path": "dirt_path_top",
    "deepslate_tile": "deepslate_tiles", "deepslate_brick": "deepslate_bricks",
    "prismarine_brick": "prismarine_bricks", "tuff_brick": "tuff_bricks",
    "polished_blackstone_brick": "polished_blackstone_bricks",
    "cut_copper": "cut_copper", "petrified_oak": "oak_planks",
    "glass_pane": "glass", "water": "water_still", "lava": "lava_still",
}
_WOODS = ["oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove",
          "cherry", "bamboo", "crimson", "warped", "pale_oak"]

# 草・葉はテクスチャがグレースケールで、ゲーム内でバイオーム色が掛かる
_TINT = {"grass_block_top": (0.49, 0.74, 0.35), "short_grass": (0.49, 0.74, 0.35),
         "tall_grass_top": (0.49, 0.74, 0.35), "fern": (0.49, 0.74, 0.35),
         "oak_leaves": (0.38, 0.6, 0.2), "jungle_leaves": (0.38, 0.6, 0.2),
         "acacia_leaves": (0.38, 0.6, 0.2), "dark_oak_leaves": (0.38, 0.6, 0.2),
         "mangrove_leaves": (0.38, 0.6, 0.2), "vine": (0.38, 0.6, 0.2),
         "spruce_leaves": (0.38, 0.6, 0.38), "birch_leaves": (0.5, 0.65, 0.33),
         "water_still": (0.25, 0.46, 0.89)}


@lru_cache(maxsize=1)
def _jar():
    """テクスチャを読む Minecraft 本体の jar（設定の minecraft_jar）。"""
    return zipfile.ZipFile(config.minecraft_jar())


@lru_cache(maxsize=1)
def _tex_names():
    return {n[len(TEX):-4] for n in _jar().namelist() if n.startswith(TEX) and n.endswith(".png")}


def _texture_for(block: str):
    """ブロック名（minecraft: なし、プロパティなし）→ テクスチャ名。見つからなければ None。"""
    names = _tex_names()
    base = _SHAPE_SUFFIX.sub("", block)
    for w in _WOODS:  # oak_stairs → oak_planks
        if base == w:
            base = f"{w}_planks"
    base = _ALIAS.get(base, base)
    for cand in (base, f"{base}_side", f"{base}_top", f"{base}_planks", f"{base}s", f"{base}_block"):
        if cand in names:
            return cand
    return None


@lru_cache(maxsize=None)
def texture_rgba(tex: str) -> np.ndarray:
    """テクスチャを (H,W,4) float 0..1 で返す（アニメーションは1コマ目）。"""
    img = Image.open(io.BytesIO(_jar().read(f"{TEX}{tex}.png"))).convert("RGBA")
    a = np.asarray(img, dtype=np.float32) / 255.0
    w = a.shape[1]
    a = a[:w]  # 縦長アニメーションテクスチャは先頭の正方形だけ
    tint = _TINT.get(tex)
    if tint:
        a[..., :3] *= np.array(tint, dtype=np.float32)
    return a


@lru_cache(maxsize=None)
def block_rgb(block: str):
    """ブロック名 → 平均 RGB (0..255)。不明なら None。"""
    block = block.replace("minecraft:", "").split("[")[0]
    tex = _texture_for(block)
    if tex is None:
        return None
    a = texture_rgba(tex)
    alpha = a[..., 3:4]
    if alpha.sum() == 0:
        return None
    rgb = (a[..., :3] * alpha).sum(axis=(0, 1)) / alpha.sum()
    return tuple(int(round(v * 255)) for v in rgb)


# ---------- 写真の色 → ブロック（Lab 最近傍） ----------

def rgb_to_lab(rgb) -> np.ndarray:
    """sRGB (0..255, (...,3)) → CIE Lab。"""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def nearest_block(rgb, palette):
    """palette（ブロック名リスト）の中から rgb に最も近いものを返す。"""
    cols = np.array([block_rgb(b) for b in palette], dtype=np.float64)
    d = np.linalg.norm(rgb_to_lab(cols) - rgb_to_lab(np.asarray(rgb, dtype=np.float64)), axis=-1)
    return palette[int(np.argmin(d))]


if __name__ == "__main__":
    for b in ["bricks", "dark_oak_stairs", "red_wool", "white_concrete", "glass", "grass_block",
              "polished_andesite", "spruce_planks", "oak_slab", "smooth_stone", "cobblestone_wall",
              "stone_brick_slab", "black_concrete", "gray_concrete", "glowstone", "brick_slab"]:
        print(f"{b:22s} {_texture_for(b)!s:22s} {block_rgb(b)}")
