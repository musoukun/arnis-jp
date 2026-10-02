"""
ガスト 堺北花田店（OSM way 389051949）。ストリートビュー 2024年6月の写真1枚から作った作例（v6）。
ユーザー評価「かなりクオリティが高くて感動した」。新しい建物はこのファイルをひな形にする。

写真の読み取り（物差し: 自転車の人の頭 1.6m、駐輪ラック 0.75m）:
  軒（柱の上端）実寸 3.7m → 5 マス、屋根の頂部 実寸 5.5m → 7.5 マス（×1.35、scale.py）
  積み重なり（下から）: 窓 → 縞のひさし → 赤い帯 → 寄棟の屋根（正面に黒い板の看板）
  南西の凹み = 入口ポーチ（赤い柱、赤茶のタイル、縦看板「から好し」）
  外まわり: レンガの植え込み＋生け垣、のぼり旗、駐輪ラック、電柱、ポール看板、点字ブロック
"""

import parts
from parcel import cells_in

G = -62  # run.py がワールドの地面を測って上書きする
WAY = 389051949           # 建物
LANDUSE = 1052342556      # 敷地の元（landuse=retail）
EXCLUDE = [881375790]     # 敷地から外す（地下鉄出入口の屋根）

# ---- 仕様（parts.build が読む） ----
STACK = ["glass", "glass", "glass", "frame+awning", "band"]   # 柱 5 マス
ROOF = {"type": "hip", "rise": 2.5}                            # 頂部 = 5 + 1 + 2.5 ≒ 8 マス
WINDOW_FACES = {"w", "n", "s"}      # 東は裏（写真に無いので無地）
PILLAR_EVERY = 3
DOOR_FACE = "w"                     # 入口の扉はポーチ（西側）に面した壁
PAL = {}                            # 素材は parts.DEFAULT_PAL のまま（コンクリート→石レンガ 等）

ROOF_SIGN_Z = (473, 478)  # 屋根正面の看板の z 範囲（写真では西面の中央より南寄り、6マス）


def site_cells(geo):
    """landuse ∪ 屋根のまわり5マスを、歩道（x<422）・駐車場通路（x>452）の手前で切る。"""
    bld, roof = footprint(geo)
    around = {(x + dx, z + dz) for (x, z) in roof for dx in range(-5, 6) for dz in range(-5, 6)}
    lot = cells_in(geo.polygon(LANDUSE))
    excluded = set().union(*(cells_in(geo.polygon(w)) for w in EXCLUDE))
    return {(x, z) for (x, z) in (lot | around)
            if 422 <= x <= 452 and 458 <= z <= 494 and (x, z) not in excluded}


def footprint(geo):
    """(建物, 屋根)。屋根は南西の凹み（入口ポーチ）も覆う。南東の凹みは裏の作業場で覆わない。"""
    bld = cells_in(geo.polygon(WAY))
    xs = [x for x, _ in bld]
    zs = [z for _, z in bld]
    x0, z1 = min(xs), max(zs)
    south_wing_x0 = min(x for x, z in bld if z == z1)
    notch = {(x, z) for x in range(x0, south_wing_x0) for z in range(z1 - 7, z1 + 1)
             if (x, z) not in bld and any((x, zz) in bld for zz in range(z - 8, z))}
    return bld, bld | notch


def _porch_corner(porch):
    return min(x for x, _ in porch), max(z for _, z in porch)  # 南西の角


def signs(geo):
    """地図アートの看板 [(名前, 列, 行, 左上の額縁 (x,y,z))]。どれも西向き、列は +z へ。支えは x+1。"""
    bld, roof = footprint(geo)
    porch, ring = roof - bld, parts.ring_of(roof)
    west_eave = {}
    for (x, z) in ring:
        if (x + 1, z) in roof:
            west_eave[z] = min(west_eave.get(z, x), x)
    z0, z1 = ROOF_SIGN_Z
    fx = min(west_eave[z] for z in range(z0, z1 + 1))
    top = G + len(STACK)
    out = [("roof", z1 - z0 + 1, 1, (fx, top + 1, z0))]          # 屋根の正面（軒先の列）
    if porch:
        cx, cz = _porch_corner(porch)
        out.append(("karayoshi", 1, 2, (cx - 2, G + 3, cz - 2)))  # 入口の縦看板
        px, pz = cx + 2, cz + 3
        out.append(("pole_logo", 2, 2, (px - 1, G + 8, pz - 1)))  # ポール看板
        out.append(("pole_sub", 2, 1, (px - 1, G + 6, pz - 1)))
    return out


SIGN_BACKING = {  # 看板の裏（額縁が見えなくても看板の色の塊に見える）
    "roof": "black_concrete",
    "karayoshi": "white_concrete",
    "pole_logo": "red_concrete",
    "pole_sub": "white_concrete",
}


def sign_images():
    """看板の画像（列 x 行ブロック分）。写真の看板の色と配置をなぞる。"""
    from PIL import ImageDraw
    import map_art as M
    imgs = {"roof": M.text_image([("レストラン", (240, 200, 40, 255), 0.5),
                                  ("ガスト", (255, 255, 255, 255), 0.95)], 6, 1, bg=(15, 15, 15, 255))}
    logo = M.text_image([("ガスト", (255, 255, 255, 255), 0.42)], 2, 2, bg=(0, 0, 0, 0))
    pole = logo.copy()
    pole.paste((250, 250, 250, 255), (0, 0, *pole.size))
    d = ImageDraw.Draw(pole)
    W, H = pole.size
    d.rectangle((0, 0, W - 1, H - 1), outline=(200, 30, 30, 255), width=18)
    d.ellipse((24, 44, W - 24, H - 44), fill=(210, 30, 30, 255))
    pole.alpha_composite(logo)
    imgs["pole_logo"] = pole
    imgs["pole_sub"] = M.text_image([("から好し", (20, 20, 20, 255), 0.7)], 2, 1, bg=(250, 250, 250, 255))
    imgs["karayoshi"] = M.vertical_text_image("から好し", 1, 2, fg=(20, 20, 20, 255), bg=(250, 250, 250, 255),
                                              top_band=(0.18, (210, 30, 30, 255)))
    return imgs


# 写真と同じ視点（2024年6月の広角）。run.py preview が描く
CAMERAS = {
    "street": dict(rel_pos=(416.5, 1 + 1.7, 481.0), yaw=-102.0, pitch=0.0, vfov=77, width=930, height=425),
}


def extras(c):
    """外まわり。写真に写っているものだけ。"""
    G, P = c.G, c.pal
    bld, porch = c.bld, c.porch
    if porch:
        cx, cz = _porch_corner(porch)
        pz0 = min(z for _, z in porch)
        # 入口前の赤茶のタイルと、歩道から入口へ向かう点字ブロック
        parts.ground(c, [(x, z) for x in range(423, cx) for z in range(pz0, cz + 1)], P["apron"])
        parts.ground(c, [(x, (pz0 + cz) // 2) for x in range(423, cx)], P["tactile"])
        # 入口の赤い柱（5 マス）と縦看板の頭・根元（額縁の下も埋めて浮かせない）
        parts.pole(c, cx, cz, 5, P["band"])
        c.put(cx - 1, G + 4, cz - 2, P["band"])
        c.put(cx - 1, G + 1, cz - 2, P["band"])
        c.put(cx - 2, G + 1, cz - 2, P["band"])
    # 植え込み（西面・南面）、木1本（窓を隠さない所）
    west_x = min(x for x, _ in bld)
    porch_z0 = min(z for _, z in porch) if porch else max(z for _, z in bld)
    west = parts.planter(c, {(x, z) for x in range(423, west_x - 1)
                             for z in range(min(z for _, z in bld) + 1, porch_z0 - 1)})
    south_z = max(z for _, z in bld)
    sw_x = min(x for x, z in bld if z == south_z)
    parts.planter(c, {(x, z) for x in range(sw_x + 2, sw_x + 13) for z in range(south_z + 2, south_z + 4)})
    parts.small_tree(c, 425, 468, west)
    parts.nobori(c, [(424, 467), (424, 471), (424, 474), (424, 477)])
    parts.bike_racks(c, [(427, 481), (427, 483), (427, 485)])
    parts.pole(c, 423, 479, 12)                     # 電柱
    if porch:
        parts.pole(c, cx + 2, cz + 3, 5)            # ポール看板の柱
