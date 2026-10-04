"""
実寸 → ブロック数の換算。

Minecraft のブロックは現実の部品より粗い（どんなに細い部品も最低1マス）。実寸どおり 1m=1ブロックだと
窓・枠・ひさし・帯が入りきらず、低く潰れて見える。そこでワールド全体を 1.4 倍で作る（arnis --scale 1.4）。
道路・敷地・建物の平面・高架の桁下が一緒に 1.4 倍になるので、写真から測った実寸にも同じ倍率を掛ければ
幅も高さもまわりと揃う。正解例ガスト 堺北花田（柱5マス・屋根の頂部 8〜9マス）から決めた:
  1) 実寸[m] × ワールドの縮尺（world_mapping.json の scale、1.4）を四捨五入。高さにも幅にも掛ける
  2) 型ごとの最低マス数で下を支える（店舗1階の柱 5、上の階は1階分 4）
  3) 寄棟・切妻の屋根の頂部は「柱 + 3」が目安
平面（建物の形・敷地）は OSM のポリゴンをそのまま使う（ワールドの縮尺で既に広がっている）。
"""

import json

from world_reader import WORLD

WORLD_SCALE = json.loads((WORLD / "world_mapping.json").read_text(encoding="utf-8"))["scale"]
MIN_SHOP_GROUND_FLOOR = 5   # 店舗の1階（地面〜軒・帯の上端）
MIN_UPPER_FLOOR = 4         # 2階以上の1階分
ROOF_RISE_OVER_PILLAR = 3   # 寄棟・切妻: 頂部 = 柱 + 3


def blocks(real_m: float, minimum: int = 1) -> int:
    """実寸[m]（高さでも幅でも）→ ブロック数（× ワールドの縮尺 を四捨五入、最低 minimum）。"""
    return max(minimum, round(real_m * WORLD_SCALE))


def shop_ground_floor(eave_m: float) -> int:
    return blocks(eave_m, MIN_SHOP_GROUND_FLOOR)


def upper_floor(storey_m: float) -> int:
    return blocks(storey_m, MIN_UPPER_FLOOR)


if __name__ == "__main__":
    print("ワールドの縮尺:", WORLD_SCALE)
    print("ガスト: 1階の柱", shop_ground_floor(3.7), "/ 屋根の頂部", shop_ground_floor(3.7) + ROOF_RISE_OVER_PILLAR,
          "/ 窓の柱間 3m →", blocks(3.0))
    print("KFC  : 1階の柱", shop_ground_floor(3.2), "/ 上階の箱", upper_floor(2.4), "→ 頂部",
          shop_ground_floor(3.2) + upper_floor(2.4))
