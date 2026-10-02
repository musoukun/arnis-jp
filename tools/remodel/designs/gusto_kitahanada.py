"""
ガスト 堺北花田店（OSM way 389051949）の設計。

写真（doc/kitahanada/gasuto.png, ストリートビュー 2024年6月/8月）から読み取った構成:
  - 平屋。焦げ茶の緩い勾配の屋根が外周を一周し、中央は平ら
  - 軒の下に赤い帯 → 赤白縞のひさし → 濃い色の窓枠の大きな窓
  - 南西の凹み = 入口ポーチ（黒い柱、赤い壁、レンガ色の階段、「から好し」の縦看板）
  - 西面の屋根に「レストラン ガスト」の看板（白い大文字）
  - 西・南にレンガの植え込みと生け垣、のぼり旗、ポール看板

高さ（G = 敷地の地面 Y）:
  G    : 敷地のタイル / 建物の基礎
  G+1  : 床（室内は1段上がる）・レンガの腰壁・ポーチの階段
  G+2,3: 窓（2段）
  G+4  : 窓の上の枠 ＋ ひさし（壁から1マス外）
  G+5  : 赤い帯（壁の線と、1マス外の軒先）・天井
  G+6,7: 屋根の勾配（ハーフブロックで 1:2）、中央は平ら
  G+6..10: 看板の文字（西面の軒先）
"""

import random

from parcel import cells_in, distance_inward, outline

G = -62  # 既定値。run_gusto.py がワールドの地面を測って上書きする
WAY = 389051949
LANDUSE = 1052342556
CANOPY = 881375790  # 地下鉄出入口の屋根（敷地外。触らない）

# 窓とひさしを付ける面（東は裏側なので無地）
WINDOW_FACES = {"w", "n", "s"}

PAL = {
    "roof_slab": "deepslate_tile_slab",
    "band": "red_concrete",
    "awning": ("red_wool", "white_wool"),
    "frame": "polished_blackstone",
    "glass": "gray_stained_glass",
    "plinth": "bricks",
    "plain_wall": "smooth_sandstone",
    "entrance_wall": "red_terracotta",
    "floor": "birch_planks",
    "porch_floor": "polished_granite",
    "step": "polished_granite_stairs",
    "ceiling": "smooth_quartz",
    "light": "sea_lantern",
    "pave": "mud_bricks",
    "foundation": "smooth_stone",
    "planter_edge": "brick_slab",
    "hedge": "oak_leaves[persistent=true]",
    "letter": "white_concrete",
    "letter_shadow": "black_concrete",
    "sign_red": "red_concrete",
    "sign_white": "white_concrete",
    "pole": "polished_blackstone_wall",
}

# 看板「ガスト」5段（上から）。西を向いて読むので、列が増えるほど南（+z）
GLYPHS = {
    "ガ": [".#.#.#",
           "#####.",
           ".#..#.",
           ".#..#.",
           "#..##."],
    "ス": ["#####",
           "...#.",
           "..#..",
           ".#.#.",
           "#...#"],
    "ト": ["#..",
           "##.",
           "#.#",
           "#..",
           "#.."],
}


def text_bitmap(text: str):
    """文字列 → [(col,row)] の点。row 0 が一番上。"""
    pts, col = [], 0
    for ch in text:
        g = GLYPHS[ch]
        for r, line in enumerate(g):
            for c, v in enumerate(line):
                if v == "#":
                    pts.append((col + c, r))
        col += len(g[0]) + 1
    return pts, col - 1


def site_cells(geo):
    """施工範囲 = landuse と建物まわり5マスの和集合を、道路・駐車場通路の手前で切ったもの。"""
    bld = cells_in(geo.polygon(WAY))
    roof = roof_cells(bld)
    around = {(x + dx, z + dz) for (x, z) in roof for dx in range(-5, 6) for dz in range(-5, 6)}
    lot = cells_in(geo.polygon(LANDUSE))
    canopy = cells_in(geo.polygon(CANOPY))
    return {(x, z) for (x, z) in (lot | around)
            if 427 <= x <= 452 and 458 <= z <= 494 and (x, z) not in canopy}


def roof_cells(bld):
    """屋根は南西の凹み（ポーチ）も覆う。南東の凹みは裏の作業場として覆わない。"""
    xs = [x for x, _ in bld]
    zs = [z for _, z in bld]
    x0, z1 = min(xs), max(zs)
    # 南西の凹み: 西端から、建物の南翼の西端までの矩形
    south_wing_x0 = min(x for x, z in bld if z == z1)
    notch = {(x, z) for x in range(x0, south_wing_x0) for z in range(z1 - 7, z1 + 1)
             if (x, z) not in bld and any((x, zz) in bld for zz in range(z - 8, z))}
    return bld | notch


def design(geo, seed=7):
    rnd = random.Random(seed)
    B = {}

    def put(x, y, z, s):
        B[(x, y, z)] = s

    bld = cells_in(geo.polygon(WAY))
    roof = roof_cells(bld)
    porch = roof - bld
    site = site_cells(geo)
    wall = outline(bld)

    # ---- 地面 ----
    for (x, z) in site:
        put(x, G, z, PAL["pave"])
    for (x, z) in roof:
        put(x, G, z, PAL["foundation"])

    # ---- 床・天井 ----
    for (x, z) in bld:
        put(x, G + 1, z, PAL["floor"])
        put(x, G + 5, z, PAL["ceiling"])
        if (x % 4 == 1) and (z % 4 == 1) and (x, z) not in wall:
            put(x, G + 5, z, PAL["light"])
    for (x, z) in porch:
        put(x, G + 1, z, PAL["porch_floor"])
        put(x, G + 5, z, PAL["band"])

    # ---- 壁 ----
    # ポーチに面した壁（入口側）
    entrance = {c for c in wall if any((c[0] + dx, c[1] + dz) in porch
                                       for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
    for (x, z), dirs in wall.items():
        put(x, G + 1, z, PAL["plinth"])
        put(x, G + 4, z, PAL["frame"])
        put(x, G + 5, z, PAL["band"])
        corner = len(dirs) >= 2
        if (x, z) in entrance:
            for y in (G + 2, G + 3):
                put(x, y, z, PAL["entrance_wall"])
            continue
        glassy = bool(WINDOW_FACES & set(dirs))
        # 柱は3マスおき（面に沿った座標で決める）
        along = z if ("w" in dirs or "e" in dirs) else x
        pillar = corner or along % 3 == 0
        for y in (G + 2, G + 3):
            if glassy:
                put(x, y, z, PAL["frame"] if pillar else PAL["glass"])
            else:
                put(x, y, z, PAL["frame"] if corner else PAL["plain_wall"])

    # 入口の扉（ポーチ側の壁のうち、西向きの壁の中央2マスを開ける）
    ent_w = sorted(c for c in entrance if any((c[0] - 1, c[1]) in porch for _ in [0]))
    if ent_w:
        mid = len(ent_w) // 2
        for (x, z) in ent_w[mid - 1:mid + 1]:
            put(x, G + 2, z, "air")
            put(x, G + 3, z, "air")

    # ---- ひさし（壁の1マス外、G+4） ----
    step = {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}
    for (x, z), dirs in wall.items():
        if (x, z) in entrance:
            continue
        for d in dirs:
            if d not in WINDOW_FACES:
                continue
            ox, oz = x + step[d][0], z + step[d][1]
            if (ox, oz) in roof:
                continue
            a, b = PAL["awning"]
            put(ox, G + 4, oz, a if (ox + oz) % 2 == 0 else b)

    # ---- 軒先の赤い帯と屋根 ----
    ring = {(x + dx, z + dz) for (x, z) in roof for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))} - roof
    ring |= {(x + dx, z + dz) for (x, z) in roof for dx in (-1, 1) for dz in (-1, 1)} - roof  # 角も
    eave = roof | ring
    for (x, z) in ring:
        put(x, G + 5, z, PAL["band"])
    dist = distance_inward(eave)
    slab = PAL["roof_slab"]
    for (x, z), d in dist.items():
        if d == 0:
            put(x, G + 6, z, f"{slab}[type=bottom]")
        elif d == 1:
            put(x, G + 6, z, f"{slab}[type=top]")
        elif d == 2:
            put(x, G + 7, z, f"{slab}[type=bottom]")
        else:
            put(x, G + 7, z, f"{slab}[type=top]")

    # ---- 看板「ガスト」（西面の軒先、南北の中央より少し南） ----
    pts, width = text_bitmap("ガスト")
    west_eave_x = {}
    for (x, z) in ring:
        if (x + 1, z) in roof:
            west_eave_x[z] = min(west_eave_x.get(z, x), x)
    z_center = 476
    z0 = z_center - width // 2
    letters = set()
    for c, r in pts:
        z = z0 + c
        y = G + 10 - r
        x = west_eave_x.get(z)
        if x is None:
            continue
        letters.add((x, y, z))
        put(x, y, z, PAL["letter"])
    for (x, y, z) in letters:  # 右下に影を付けて読みやすくする
        sx, sy, sz = x, y - 1, z + 1
        if (sx, sy, sz) not in letters and sy >= G + 6:
            put(sx, sy, sz, PAL["letter_shadow"])

    # ---- ポーチ: 角の柱、階段、「から好し」の縦看板 ----
    pxs = [x for x, _ in porch]
    pzs = [z for _, z in porch]
    if porch:
        cx, cz = min(pxs), max(pzs)  # 南西の角
        for y in range(G + 1, G + 5):
            put(cx, y, cz, PAL["frame"])
        for (x, z) in porch:
            if (x - 1, z) not in roof and (x - 1, z) in site:
                put(x - 1, G + 1, z, f"{PAL['step']}[facing=east,half=bottom]")
            if (x, z + 1) not in roof and (x, z + 1) in site:
                put(x, G + 1, z + 1, f"{PAL['step']}[facing=north,half=bottom]")
        # 縦看板は柱の1マス北、軒の下
        sx, sz = cx - 1, cz - 2
        if (sx, sz) in site:
            for y in range(G + 1, G + 4):
                put(sx, y, sz, PAL["sign_white"])
            put(sx, G + 4, sz, PAL["sign_red"])

    # ---- 植え込み（西面・南面） ----
    def planter(cells):
        cells = {c for c in cells if c in site and c not in eave}
        edge = outline(cells)
        for (x, z) in cells:
            if (x, z) in edge:
                put(x, G + 1, z, f"{PAL['planter_edge']}[type=bottom]")
            else:
                put(x, G, z, "grass_block")
                put(x, G + 1, z, PAL["hedge"])
                if rnd.random() < 0.45:
                    put(x, G + 2, z, PAL["hedge"])
        return cells

    west_x = min(x for x, _ in bld)
    porch_z0 = min(pzs) if porch else max(z for _, z in bld)
    west_planter = planter({(x, z) for x in range(427, west_x - 1)
                            for z in range(min(z for _, z in bld) + 1, porch_z0 - 1)})
    south_z = max(z for _, z in bld)
    sw_x = min(x for x, z in bld if z == south_z)
    south_planter = planter({(x, z) for x in range(sw_x + 2, sw_x + 13)
                             for z in range(south_z + 2, south_z + 4)})

    # 細い小さな木（植え込みの中に2本）: 幹2段＋頭に葉
    for (tx, tz) in [(428, 469), (428, 477)]:
        if (tx, tz) in west_planter:
            put(tx, G + 1, tz, "oak_log")
            put(tx, G + 2, tz, "oak_log")
            put(tx, G + 3, tz, PAL["hedge"])
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p = (tx + dx, tz + dz)
                if p in site and p not in eave:
                    put(p[0], G + 3, p[1], "azalea_leaves[persistent=true]")

    # のぼり旗（植え込みの縁、西向き = rotation 4）
    for (fx, fz), color in [((427, 467), "yellow"), ((427, 471), "white"),
                            ((427, 474), "lime"), ((427, 478), "white")]:
        if (fx, fz) in site:
            put(fx, G + 2, fz, f"{color}_banner[rotation=4]")
            put(fx, G + 1, fz, "polished_andesite")

    # 駐輪ラック（ポーチ前の広場）
    for (bx, bz) in [(428, 481), (428, 483)]:
        if (bx, bz) in site and (bx, bz) not in eave:
            put(bx, G + 1, bz, "iron_bars")

    # ---- ポール看板（ポーチの南、西を向いた面） ----
    px, pz = (min(pxs) + 2, max(pzs) + 3) if porch else (432, 490)
    if (px, pz) in site:
        for y in range(G + 1, G + 7):
            put(px, y, pz, PAL["pole"])
        board = [  # 上から。列は z 方向（北→南）
            "RRRRR",
            "RWWWR",
            "RWRWR",
            "RWWWR",
            "RRRRR",
            "WWWWW",
        ]
        for r, line in enumerate(board):
            for c, v in enumerate(line):
                z = pz - 2 + c
                y = G + 12 - r
                if (px, z) in site:
                    put(px, y, z, PAL["sign_red"] if v == "R" else PAL["sign_white"])
    return B
