"""
リージョンファイル(.mca)を直接読んで、指定範囲のブロックを取り出す。

サーバー稼働中に読むときは、先に RCON で `save-all flush` してディスクに書き出しておくこと。
1.18+ のチャンク形式（sections[].block_states.palette / data）に対応。
"""

import io
import math
import zlib
from pathlib import Path

import nbtlib

ROOT = Path(__file__).resolve().parents[2]
WORLD = ROOT / "minecraft-server" / "world"


def _state_string(entry) -> str:
    """palette エントリ → 'minecraft:oak_stairs[facing=east,half=bottom]' 形式の文字列。"""
    name = str(entry["Name"])
    props = entry.get("Properties")
    if not props:
        return name
    inner = ",".join(f"{k}={props[k]}" for k in sorted(props))
    return f"{name}[{inner}]"


def _read_chunk_nbt(region_path: Path, cx: int, cz: int):
    """リージョンファイルから1チャンク分のNBTを返す。無ければ None。"""
    with open(region_path, "rb") as f:
        header = f.read(4096)
        idx = 4 * ((cx & 31) + (cz & 31) * 32)
        loc = int.from_bytes(header[idx:idx + 3], "big")
        if loc == 0:
            return None
        f.seek(loc * 4096)
        length = int.from_bytes(f.read(4), "big")
        compression = f.read(1)[0]
        data = f.read(length - 1)
    if compression == 2:
        raw = zlib.decompress(data)
    else:
        raise ValueError(f"未対応の圧縮形式: {compression}")
    return nbtlib.File.parse(io.BytesIO(raw))


def _decode_section(section):
    """1セクション(16x16x16)を palette と 4096 要素のインデックス列にして返す。"""
    bs = section.get("block_states")
    if bs is None:
        return None, None
    palette = [_state_string(p) for p in bs["palette"]]
    if len(palette) == 1 or "data" not in bs:
        return palette, None  # 全部同じブロック
    bits = max(4, math.ceil(math.log2(len(palette))))
    per_long = 64 // bits
    mask = (1 << bits) - 1
    indices = []
    for value in bs["data"]:
        v = int(value) & 0xFFFFFFFFFFFFFFFF  # 符号付き → 符号なし
        for _ in range(per_long):
            indices.append(v & mask)
            v >>= bits
            if len(indices) == 4096:
                break
        if len(indices) == 4096:
            break
    return palette, indices


class WorldSnapshot:
    """範囲指定で読み込んだブロックの塊。get(x,y,z) で状態文字列を返す。"""

    def __init__(self, blocks: dict, bounds):
        self.blocks = blocks  # (x,y,z) -> state string（air は入れない）
        self.bounds = bounds  # (x0, y0, z0, x1, y1, z1) 両端含む

    def get(self, x, y, z) -> str:
        return self.blocks.get((x, y, z), "minecraft:air")


def load_area(x0, z0, x1, z1, y0=-64, y1=-30, world: Path = WORLD) -> WorldSnapshot:
    """x0..x1, z0..z1, y0..y1（両端含む）の範囲を読む。"""
    blocks = {}
    for cx in range(x0 >> 4, (x1 >> 4) + 1):
        for cz in range(z0 >> 4, (z1 >> 4) + 1):
            region = world / "region" / f"r.{cx >> 5}.{cz >> 5}.mca"
            if not region.exists():
                continue
            chunk = _read_chunk_nbt(region, cx, cz)
            if chunk is None:
                continue
            for section in chunk.get("sections", []):
                sy = int(section["Y"])
                if sy * 16 + 15 < y0 or sy * 16 > y1:
                    continue
                palette, indices = _decode_section(section)
                if palette is None:
                    continue
                for i in range(4096):
                    state = palette[indices[i]] if indices else palette[0]
                    if state == "minecraft:air":
                        continue
                    lx, lz, ly = i & 15, (i >> 4) & 15, i >> 8
                    x, y, z = cx * 16 + lx, sy * 16 + ly, cz * 16 + lz
                    if x0 <= x <= x1 and z0 <= z <= z1 and y0 <= y <= y1:
                        blocks[(x, y, z)] = state
    return WorldSnapshot(blocks, (x0, y0, z0, x1, y1, z1))


if __name__ == "__main__":
    # 動作確認: ガスト周辺のブロック種別を数える
    from collections import Counter
    snap = load_area(420, 705, 470, 750)
    c = Counter(s.split("[")[0] for s in snap.blocks.values())
    for name, n in c.most_common(40):
        print(f"{n:6d} {name}")
