"""
建物の部品ライブラリ。設計ファイル（designs/*.py）の「仕様」から建物を組み立てる。

設計ファイルが持つもの（モジュール変数・関数）:
  G               地面の Y（run.py がワールドを測って上書き）
  PAL             素材（下の DEFAULT_PAL を上書きする分だけ書けばよい）
  STACK           壁の段（下から）。例: ["glass", "glass", "glass", "frame+awning", "band"]
  WINDOW_FACES    窓とひさしを付ける面 {"n","s","w","e"}（写っていない面は入れない）
  PILLAR_EVERY    窓の柱の間隔（マス）
  ROOF            {"type": "hip"|"gable"|"flat", "rise": 段数（ハーフ単位で 0.5 刻み）, "ridge": "x"|"z"}
  DOOR_FACE       入口の扉を開ける向き（ポーチに面した壁のうち、この向きに開いた壁）
  footprint(geo)  -> (建物セル, 屋根セル)  屋根セル − 建物セル = ポーチ（屋根付きの凹み）
  site_cells(geo) -> 施工してよいセル
  signs(geo)      -> [(名前, 列, 行, 左上の額縁の位置)]（無ければ []）
  SIGN_BACKING    {名前: 看板の裏のブロック}
  extras(ctx)     外まわり（植え込み・のぼり・電柱など）。ctx.put で置く

STACK の段の種類:
  glass         窓（PILLAR_EVERY ごとに柱、窓は1マス奥に引っ込める）。窓の無い面は無地の壁
  solid         無地の壁
  frame         窓の上枠など（frame 素材）
  frame+awning  上枠 ＋ 外側1マスに縞のひさし（窓の面だけ）
  frame+balcony 上枠 ＋ 外側1マスに張り出し（ベランダ・庇の床、窓の面だけ）
  band          帯（band 素材）。最上段なら軒先の輪にも帯を回す
最上段の高さに天井、その上に屋根が乗る。
"""

import random

from parcel import cells_in, distance_inward, outline

STEP = {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}

# 素材の対応表（現実の素材 → ブロック）。設計ファイルの PAL で必要な分だけ上書きする
DEFAULT_PAL = {
    "pave": "stone_bricks",              # コンクリート舗装
    "apron": "polished_granite",         # 店先の赤茶のタイル
    "tactile": "bamboo_planks",          # 黄色い点字ブロック
    "floor": "birch_planks",
    "ceiling": "smooth_quartz",
    "light": "sea_lantern",
    "porch_floor": "polished_granite",
    "frame": "polished_blackstone",      # 窓枠・暗い柱
    "glass": "gray_stained_glass",
    "plain_wall": "smooth_sandstone",
    "entrance_wall": "red_terracotta",
    "band": "red_concrete",
    "awning": ("red_wool", "white_wool"),
    "balcony": "smooth_stone_slab[type=bottom]",
    "roof_slab": "deepslate_tile_slab",
    "roof_flat": "smooth_stone",
    "parapet": "stone_brick_wall",
    "planter_edge": "bricks",
    "hedge": "oak_leaves[persistent=true]",
    "tree_log": "oak_log",
    "tree_leaves": "azalea_leaves[persistent=true]",
    "rack": "iron_bars",
    "pole": "stone_brick_wall",          # コンクリートの柱・電柱
}


class Ctx:
    """組み立て中の状態。extras(ctx) からも使う。"""

    def __init__(self, spec, geo, seed):
        self.spec = spec
        self.G = spec.G
        self.pal = {**DEFAULT_PAL, **getattr(spec, "PAL", {})}
        self.rnd = random.Random(seed)
        self.B = {}
        self.site = spec.site_cells(geo)
        if hasattr(spec, "footprint"):
            self.bld, self.roof = spec.footprint(geo)
        else:  # 既定: 屋根は建物の形そのまま
            self.bld = cells_in(geo.polygon(spec.WAY))
            self.roof = set(self.bld)
        self.porch = self.roof - self.bld
        self.ring = ring_of(self.roof)
        self.eave = self.roof | self.ring
        self.wall = outline(self.bld)
        self.entrance = {c for c in self.wall if any((c[0] + dx, c[1] + dz) in self.porch
                                                     for dx, dz in STEP.values())}
        self.top = self.G + len(spec.STACK)  # 最上段（天井・帯）の Y

    def put(self, x, y, z, s):
        self.B[(x, y, z)] = s

    def ok(self, x, z):
        """敷地内で、軒の下でもない（外まわりを置ける）セルか。"""
        return (x, z) in self.site and (x, z) not in self.eave


def ring_of(roof):
    """屋根の外側1マスの輪（軒先）。角も含む。"""
    ring = {(x + dx, z + dz) for (x, z) in roof for dx, dz in STEP.values()} - roof
    ring |= {(x + dx, z + dz) for (x, z) in roof for dx in (-1, 1) for dz in (-1, 1)} - roof
    return ring


# ---------------- 建物の本体 ----------------

def build(spec, geo, seed=7):
    c = Ctx(spec, geo, seed)
    G, P, put = c.G, c.pal, c.put
    stack = spec.STACK
    faces = set(spec.WINDOW_FACES)
    every = getattr(spec, "PILLAR_EVERY", 3)

    # 地面・床・天井
    for (x, z) in c.site:
        put(x, G, z, P["pave"])
    for (x, z) in c.bld:
        put(x, G, z, P["floor"])
        put(x, c.top, z, P["ceiling"])
        if (x % 4 == 1) and (z % 4 == 1) and (x, z) not in c.wall:
            put(x, c.top, z, P["light"])
    for (x, z) in c.porch:
        put(x, G, z, P["porch_floor"])
        put(x, c.top, z, P["band"])

    # 壁（上枠・帯の段を先に、窓の段を後に）
    glass_rows = [G + 1 + i for i, k in enumerate(stack) if k in ("glass", "solid")]
    for (x, z), dirs in c.wall.items():
        for i, kind in enumerate(stack):
            y = G + 1 + i
            if kind.startswith("frame"):
                put(x, y, z, P["frame"])
            elif kind == "band":
                put(x, y, z, P["band"])
        corner = len(dirs) >= 2
        if (x, z) in c.entrance:
            for y in glass_rows:
                put(x, y, z, P["entrance_wall"])
            continue
        glassy = bool(faces & set(dirs))
        along = z if ("w" in dirs or "e" in dirs) else x
        pillar = corner or along % every == 0
        for y in glass_rows:
            kind = stack[y - G - 1]
            if kind == "solid" or not glassy:
                put(x, y, z, P["frame"] if corner else P["plain_wall"])
            elif pillar:
                put(x, y, z, P["frame"])
            else:
                ix, iz = x - STEP[dirs[0]][0], z - STEP[dirs[0]][1]
                if (ix, iz) in c.bld and (ix, iz) not in c.wall:
                    put(x, y, z, "air")          # 外側に凹み（上枠の下に影）
                    put(ix, y, iz, P["glass"])
                else:
                    put(x, y, z, P["glass"])

    # 入口の扉（ポーチに面した DOOR_FACE 向きの壁の中央2マス）
    door_face = getattr(spec, "DOOR_FACE", None)
    if door_face:
        dx, dz = STEP[door_face]
        doors = sorted(w for w in c.entrance if (w[0] + dx, w[1] + dz) in c.porch)
        if len(doors) >= 2:
            mid = len(doors) // 2
            for (x, z) in doors[mid - 1:mid + 1]:
                put(x, G + 1, z, "air")
                put(x, G + 2, z, "air")

    # ひさし・張り出し（窓の面の外側1マス）
    for i, kind in enumerate(stack):
        if kind not in ("frame+awning", "frame+balcony"):
            continue
        y = G + 1 + i
        for (x, z), dirs in c.wall.items():
            if (x, z) in c.entrance:
                continue
            for d in dirs:
                if d not in faces:
                    continue
                ox, oz = x + STEP[d][0], z + STEP[d][1]
                if (ox, oz) in c.roof:
                    continue
                if kind == "frame+awning":
                    a, b = P["awning"]
                    put(ox, y, oz, a if (ox + oz) % 2 == 0 else b)
                else:
                    put(ox, y, oz, P["balcony"])

    # 軒先の帯（最上段が band のとき）と屋根
    if stack[-1] == "band":
        for (x, z) in c.ring:
            put(x, c.top, z, P["band"])
    roof(c, spec.ROOF)

    # 看板の裏（額縁の支え兼、色の塊）
    for name, cols, rows, (fx, fy, fz) in (spec.signs(geo) if hasattr(spec, "signs") else []):
        for col in range(cols):
            for r in range(rows):
                put(fx + 1, fy - r, fz + col, spec.SIGN_BACKING[name])
                put(fx, fy - r, fz + col, "air")  # 額縁の場所

    if hasattr(spec, "extras"):
        spec.extras(c)
    return c.B


def roof(c, R):
    """屋根。rise は段数（ハーフ単位、0.5 刻み）。軒先の輪から内側へ 1:2 で上がる。"""
    y0 = c.top + 1
    slab = c.pal["roof_slab"]
    kind = R.get("type", "hip")
    if kind == "flat":
        for (x, z) in c.roof:
            c.put(x, c.top, z, c.pal["roof_flat"])
        for (x, z) in outline(c.roof):
            c.put(x, y0, z, c.pal["parapet"])  # 1マスの手すり壁
        return
    cap = max(0, int(round(R.get("rise", 2.5) * 2)) - 1)  # ハーフ何枚分上がるか − 1
    if kind == "hip":
        dist = distance_inward(c.eave)
    else:  # gable: 棟の向き（ridge）に直交する方向の距離だけで上げる
        axis = R.get("ridge", "x")
        dist = {}
        for (x, z) in c.eave:
            line = [(x, zz) for zz in range(z - 200, z + 201)] if axis == "x" else \
                   [(xx, z) for xx in range(x - 200, x + 201)]
            inside = [p for p in line if p in c.eave]
            k = (z if axis == "x" else x)
            lo = min(p[1] if axis == "x" else p[0] for p in inside)
            hi = max(p[1] if axis == "x" else p[0] for p in inside)
            dist[(x, z)] = min(k - lo, hi - k)
    for (x, z), d in dist.items():
        dd = min(d, cap)
        c.put(x, y0 + dd // 2, z, f"{slab}[type={'bottom' if dd % 2 == 0 else 'top'}]")


# ---------------- 外まわりの部品（extras から使う） ----------------

def planter(c, cells, hedge_second_row=0.6):
    """レンガの縁（1マス）＋生け垣（1段目は全部、2段目は割合）。窓とひさしを隠さないよう2段まで。"""
    cells = {p for p in cells if c.ok(*p)}
    edge = outline(cells)
    for (x, z) in cells:
        if (x, z) in edge:
            c.put(x, c.G + 1, z, c.pal["planter_edge"])
        else:
            c.put(x, c.G, z, "grass_block")
            c.put(x, c.G + 1, z, c.pal["hedge"])
            if c.rnd.random() < hedge_second_row:
                c.put(x, c.G + 2, z, c.pal["hedge"])
    return cells


def small_tree(c, x, z, allowed):
    """幹2段＋頭に葉（高さ 3 マス）。allowed（植え込みのセル）の中だけ。"""
    if (x, z) not in allowed:
        return
    G = c.G
    c.put(x, G + 1, z, c.pal["tree_log"])
    c.put(x, G + 2, z, c.pal["tree_log"])
    c.put(x, G + 3, z, c.pal["hedge"])
    for dx, dz in STEP.values():
        if c.ok(x + dx, z + dz):
            c.put(x + dx, G + 3, z + dz, c.pal["tree_leaves"])


def nobori(c, spots, rotation=4, color="white", accent="red"):
    """のぼり旗: 柵の柱の上に模様付きの旗（高さ約3マス）。rotation 4 = 西向き。"""
    flag = (f'minecraft:{color}_banner[rotation={rotation}]{{patterns:['
            f'{{pattern:"minecraft:flower",color:"{accent}"}},'
            f'{{pattern:"minecraft:stripe_bottom",color:"{accent}"}},'
            f'{{pattern:"minecraft:triangles_top",color:"{accent}"}}]}}')
    for (x, z) in spots:
        if (x, z) in c.site:
            c.put(x, c.G + 1, z, c.pal["rack"])
            c.put(x, c.G + 2, z, flag)


def bike_racks(c, spots):
    for (x, z) in spots:
        if c.ok(x, z):
            c.put(x, c.G + 1, z, c.pal["rack"])


def pole(c, x, z, height, material=None):
    """柱（電柱は 12 マス、看板の柱など）。"""
    if (x, z) in c.site:
        for y in range(c.G + 1, c.G + 1 + height):
            c.put(x, y, z, material or c.pal["pole"])


def ground(c, cells, material):
    """舗装の張り替え（店先のタイル・点字ブロックなど）。軒の下は除く。"""
    for (x, z) in cells:
        if c.ok(x, z):
            c.put(x, c.G, z, material)
