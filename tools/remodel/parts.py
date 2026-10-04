"""
建物の部品ライブラリ。設計ファイル（designs/*.py）の「仕様」から建物を組み立てる。

設計ファイルが持つもの（モジュール変数・関数）:
  G               地面の Y（run.py がワールドを測って上書き）
  PAL             素材（下の DEFAULT_PAL を上書きする分だけ書けばよい）
  STACK           壁の段（下から）。例: ["glass", "glass", "glass", "frame+awning", "band"]
  WINDOW_FACES    窓とひさしを付ける面 {"n","s","w","e"}（写っていない面は入れない）
  PILLAR_EVERY    窓の柱の間隔（マス）
  ROOF            {"type": "hip"|"gable"|"flat", "rise": 段数（ハーフ単位で 0.5 刻み）, "ridge": "x"|"z"}
  PLINTH          土台（基壇）の段数。0 = 床が地面と同じ。1 = レンガの土台の上に床（入口は階段で1段上がる）
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
    "plinth": "bricks",                  # 土台（基壇）
    "foundation": "smooth_stone",        # 土台の中身
    "apron": "polished_granite",         # 店先の赤茶のタイル
    "tactile": "bamboo_planks",          # 黄色い点字ブロック
    "floor": "birch_planks",
    "ceiling": "smooth_quartz",
    "light": "sea_lantern",
    "porch_floor": "polished_granite",
    "step": "brick_stairs",              # 入口の階段
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
    "door_frame": "stone_bricks",        # 自動扉の仕掛けを包むブロック（ユーザー: 回路は完全に隠す。石レンガ）
    "door_glass": "glass",               # 自動扉（ピストンで動くガラス）
    "door_plate": "polished_blackstone_pressure_plate",  # プレイヤーだけに反応
    "table": "spruce_fence",             # 机 = 柵 1本 ＋ 感圧板
    "table_top": "spruce_pressure_plate",
    "chair": "spruce_stairs",            # 椅子 = 階段
    "lantern": "lantern",                # 天井から鎖で吊る
    "chain": "iron_chain[axis=y]",       # 1.21.9 から chain → iron_chain
}


class Blocks(dict):
    """置くブロック {(x,y,z): 状態}。ordered は施工の最後に順番どおり置くもの（ピストンなど）。"""
    def __init__(self):
        super().__init__()
        self.ordered = []
        self.decor = []      # 飾り（ランタン・トーチ等）。ブロックを全部置いた後に最後に取り付ける


class Ctx:
    """組み立て中の状態。extras(ctx) からも使う。"""

    def __init__(self, spec, geo, seed):
        self.spec = spec
        self.G = spec.G
        self.pal = {**DEFAULT_PAL, **getattr(spec, "PAL", {})}
        self.rnd = random.Random(seed)
        self.B = Blocks()
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
        self.plinth = getattr(spec, "PLINTH", 0)
        self.F = self.G + self.plinth          # 床の Y（土台があれば地面より上）
        self.top = self.F + len(spec.STACK)    # 最上段（天井・帯）の Y

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


# 額縁の向き → (列が進む向き, 支えのブロックがある向き)。列は「看板を正面から見て左から右」
SIGN_DIR = {
    "west": ((0, 1), (1, 0)), "east": ((0, -1), (-1, 0)),
    "north": ((-1, 0), (0, 1)), "south": ((1, 0), (0, -1)),
}


def sign_cells(sign):
    """看板 (名前, 列, 行, 左上の額縁 (x,y,z)[, 向き]) → (行, 列, 額縁のセル, 支えのセル, 向き) を順に返す。"""
    _, cols, rows, (fx, fy, fz) = sign[:4]
    facing = sign[4] if len(sign) > 4 else "west"
    (cx, cz), (bx, bz) = SIGN_DIR[facing]
    for r in range(rows):
        for col in range(cols):
            x, z = fx + cx * col, fz + cz * col
            yield r, col, (x, fy - r, z), (x + bx, fy - r, z + bz), facing


# ---------------- 建物の本体 ----------------

def build(spec, geo, seed=7):
    c = Ctx(spec, geo, seed)
    G, F, P, put = c.G, c.F, c.pal, c.put
    stack = spec.STACK
    faces = set(spec.WINDOW_FACES)
    every = getattr(spec, "PILLAR_EVERY", 3)

    # 地面・床・天井
    for (x, z) in c.site:
        put(x, G, z, P["pave"])
    for (x, z) in c.bld:
        for y in range(G, F):
            put(x, y, z, P["plinth"] if (x, z) in c.wall else P["foundation"])  # 土台（外から見えるのは壁の下）
        put(x, F, z, P["plinth"] if (c.plinth and (x, z) in c.wall) else P["floor"])
        put(x, c.top, z, P["ceiling"])
        if (x % 4 == 1) and (z % 4 == 1) and (x, z) not in c.wall:
            put(x, c.top, z, P["light"])
    for (x, z) in c.porch:
        for y in range(G, F):
            put(x, y, z, P["plinth"])
        put(x, F, z, P["porch_floor"])
        put(x, c.top, z, P["band"])

    # 壁（上枠・帯の段を先に、窓の段を後に）
    glass_rows = [F + 1 + i for i, k in enumerate(stack) if k in ("glass", "solid")]
    for (x, z), dirs in c.wall.items():
        for i, kind in enumerate(stack):
            y = F + 1 + i
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
            kind = stack[y - F - 1]
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
                put(x, F + 1, z, "air")
                put(x, F + 2, z, "air")

    # ひさし・張り出し（窓の面の外側1マス）
    for i, kind in enumerate(stack):
        if kind not in ("frame+awning", "frame+balcony"):
            continue
        y = F + 1 + i
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
    for sign in (spec.signs(geo) if hasattr(spec, "signs") else []):
        backing = spec.SIGN_BACKING.get(sign[0])
        for _, _, frame, back, _ in sign_cells(sign):
            if backing:                      # None なら壁をそのまま支えにする（透明な文字を壁に直接載せる）
                put(*back, backing)
            put(*frame, "air")               # 額縁の場所

    if hasattr(spec, "extras"):
        spec.extras(c)
    connect(c.B)
    # 飾り（ほかのブロックに付く物）は、ブロックを全部置いてから最後に取り付ける（支えが先にあるように、下から順に）
    decor = sorted(((p, st) for p, st in c.B.items() if is_decor(st)), key=lambda t: t[0][1])
    for p, _ in decor:
        del c.B[p]
    c.B.decor = [(x, y, z, st) for (x, y, z), st in decor]
    return c.B


# 飾り: ブロックの形を持たず、ほかのブロックに付く・載る物。ブロックを置き終えてから最後に取り付ける。
# 自動扉の配線（redstone_*）は仕掛けなので含めない（ピストンより先に要る）
_DECOR_NAMES = ("lantern", "soul_lantern", "iron_chain", "flower_pot", "ladder", "lever", "tripwire_hook")
_DECOR_PARTS = ("torch", "_banner", "_button", "pressure_plate", "potted_", "candle", "_sign", "copper_lantern")


def is_decor(state):
    n = state.split("[")[0].split("{")[0].replace("minecraft:", "")
    if n.startswith("redstone") or n in ("sea_lantern", "jack_o_lantern"):
        return False
    return n in _DECOR_NAMES or any(w in n for w in _DECOR_PARTS)


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


def louver(c, height, avoid=(), material="dark_oak_trapdoor"):
    """屋上の柵・ルーバー。軒先の輪（帯の上）に、外側の面に板を立てる（開いたトラップドア）。
    壁の真上だと帯の張り出しで下の段が隠れ、柵（fence）は棒なので軽く見える。avoid（塔など）に接する所は空ける。"""
    opposite = {"n": "south", "s": "north", "w": "east", "e": "west"}
    near = {(x + dx, z + dz) for (x, z) in avoid for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
    for (x, z), faces in outline(c.ring).items():
        out = [f for f in faces if (x + STEP[f][0], z + STEP[f][1]) not in c.roof]
        if not out or (x, z) in near:
            continue
        for y in range(c.top + 1, c.top + 1 + height):
            c.put(x, y, z, f"{material}[facing={opposite[out[0]]},half=bottom,open=true]")


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


def entrance(c, cells, face, height=3, out=2, inside=2, steps="stairs", step_slab="brick_slab"):
    """入れる入口を作る（どの建物でも extras の最後に呼ぶ）。
    cells: 入口にする壁のセル、face: 外を向いた面（"n"/"s"/"w"/"e"）。
    - 床: 室内・開口は床の高さ F。土台（PLINTH）があれば、外側に段を置いて上がれるようにする
      steps="stairs": 階段ブロックで1マスずつ（従来）。steps="slab": ハーフずつ上がる（辞書の「入口の段」）
      steps="landing": 扉の前の1マスだけフルブロック（床の高さ）、その外はハーフずつ下がる（よく使う作り。辞書の「扉の前の踏み台」）
    - 開口: 床から高さ height（店舗 3、住宅 2）。壁と、奥に引っ込めた窓の列の両方を開ける
    - 通り道: 外側 out マス・内側 inside マスは、頭の高さまで障害物を消す
    プレイヤーは高さ 1.8、ジャンプで上がれるのは約 1.25。上枠は「床 + height」より下に置かない。"""
    G, F = c.G, c.F
    dx, dz = STEP[face]
    stair_facing = {"w": "east", "e": "west", "n": "south", "s": "north"}[face]  # 建物に向かって上る
    if steps == "slab":
        out = max(out, 2 * c.plinth - 1)   # ハーフの段の数だけ（最後の1枚の外は地面のまま。前にある物を消さない）
    if steps == "landing":
        out = max(out, 2 * c.plinth)       # 扉の前のフルブロック1マス＋その外のハーフ
    for (x, z) in cells:
        for k in range(-out, inside + 1):  # k<0: 外、k=0: 壁、k>0: 室内
            px, pz = x - dx * k, z - dz * k
            if k > 0 and (px, pz) not in c.bld:
                break
            if k < 0 and (px, pz) not in c.site:
                continue
            if k >= 0:
                top = F
                c.put(px, top, pz, c.pal["floor"] if k > 0 else c.pal["porch_floor"])
            elif steps in ("slab", "landing"):
                # 地面の上面からの高さ（ハーフ単位）。壁から離れるほど低い。landing は扉の前が床と同じ高さ
                halves = 2 * c.plinth + k + (1 if steps == "landing" else 0)
                full, half = max(0, halves) // 2, max(0, halves) % 2
                for i in range(full):
                    c.put(px, G + 1 + i, pz, f"{step_slab}[type=double]")
                if half:
                    c.put(px, G + 1 + full, pz, f"{step_slab}[type=bottom]")
                if halves <= 0:
                    c.put(px, G, pz, c.pal["apron"])
                top = G + full + half
            else:
                step = c.plinth + k + 1          # 壁のすぐ外が一番高い段
                top = G + max(0, step)
                if step > 0:
                    c.put(px, top, pz, f"{c.pal['step']}[facing={stair_facing},half=bottom]")
                else:
                    c.put(px, G, pz, c.pal["apron"])
            for y in range(top + 1, F + 1 + height):
                c.put(px, y, pz, "air")


# ---------------- 室内・自動扉 ----------------

FACING = {"n": "north", "s": "south", "w": "west", "e": "east"}


def furnish(c, faces, avoid=(), every=4):
    """正面から見える室内: 窓の面の内側に机（柵＋感圧板）と椅子（階段）、天井に吊ったランタン。
    窓の面の壁から 2・3・4 マス内側に「椅子・机・椅子」を every マスおきに並べる。avoid（入口・仕掛け）は空ける。"""
    F, P = c.F, c.pal
    avoid = set(avoid)
    free = lambda x, z: (x, z) in c.bld and (x, z) not in c.wall and (x, z) not in avoid
    for (x, z), dirs in c.wall.items():
        for f in dirs:
            if f not in faces:
                continue
            dx, dz = STEP[f]
            if (z if f in ("w", "e") else x) % every:
                continue
            seat_out, table, seat_in = [(x - dx * k, z - dz * k) for k in (2, 3, 4)]
            if not all(free(*p) for p in (seat_out, table, seat_in)):
                continue
            c.put(table[0], F + 1, table[1], P["table"])
            c.put(table[0], F + 2, table[1], P["table_top"])
            back = {"n": "s", "s": "n", "w": "e", "e": "w"}[f]
            c.put(seat_out[0], F + 1, seat_out[1], f"{P['chair']}[facing={FACING[f]},half=bottom]")   # 背もたれは壁側
            c.put(seat_in[0], F + 1, seat_in[1], f"{P['chair']}[facing={FACING[back]},half=bottom]")  # 背もたれは奥側
    # ランタン: 天井から鎖で吊って、窓の高さ（床 + 3）に光を見せる
    for (x, z) in c.bld:
        if (x, z) in c.wall or (x, z) in avoid or (x % 3, z % 3) != (1, 1):
            continue
        if c.top - 1 < F + 3:    # 天井が低いと、吊ったランタンが頭に当たる
            continue
        for y in range(F + 4, c.top):
            c.put(x, y, z, P["chain"])
        c.put(x, F + 3, z, f"{P['lantern']}[hanging=true]")


def auto_door(c, cells, face):
    """感圧板で開くガラスの自動扉（幅2・高さ2）。入口は「柱に挟まれた凹み」: 壁の線の左右2マスずつを柱にし、
    その1マス奥にガラスの扉。仕掛け（ピストン・トーチ・粉）は石レンガで包み、配線は床下・トーチは床の中に隠す。
    仕組み: 粘着ピストンが左右から扉のガラスを押し出して閉じている（レッドストーントーチの常時信号）。
    感圧板を踏むと床下の配線でトーチが消え、ピストンが縮んでガラスを壁の中へ引き込む＝開く。
    配線は床下（F-1）に通すので PLINTH >= 1 が必要。cells は入口の壁セル2つ、face は外を向いた面。
    戻り値: 仕掛けと通り道のセル（furnish の avoid に渡す）。"""
    G, F, P = c.G, c.F, c.pal
    if c.plinth < 1:
        print("auto_door: PLINTH = 0 では床下に配線できないので、扉を付けずに開口のままにします")
        return set()
    d0, d1 = sorted(cells)
    ox, oz = STEP[face]                      # 外向き
    wx, wz = d1[0] - d0[0], d1[1] - d0[1]    # 壁に沿った向き（d0 → d1）
    assert abs(wx) + abs(wz) == 1, "cells は隣り合った壁セル2つ"
    U = F - 1                                # 床下
    at = lambda k, n: (d0[0] + wx * k - ox * n, d0[1] + wz * k - oz * n)   # n=0 壁の線、n=1 扉の線、n=2 室内

    def put(k, n, y, s):
        x, z = at(k, n)
        c.put(x, y, z, s)

    S = P["door_frame"]                      # 仕掛けを包む石レンガ（外からも室内からも、仕掛けは見えない）
    used = set()
    # 入口の両脇は柱（壁の線に2マスずつ、帯の下まで）。ピストンはこの柱の裏に隠れる。その外の1マスは窓
    for k in (-2, -1, 2, 3):
        for y in range(F + 1, c.top):
            put(k, 0, y, P["frame"])
    for k in (-3, 4):
        for y in range(F + 1, c.top):
            put(k, 0, y, P["glass"])
    # 扉の線の両脇とその奥の列を、天井まで石レンガで埋める（ピストン・引き込んだガラス・トーチ・粉はこの中）
    for k in list(range(-4, 0)) + list(range(2, 6)):
        for n in (1, 2):
            for y in range(F + 1, c.top):
                put(k, n, y, S)
        for n in (0, 1, 2):
            used.add(at(k, n))
    for k in (0, 1):         # 扉の上は明かり取りのガラス（扉が床から3マスのガラスに見える）
        put(k, 1, F + 3, P["door_glass"])
    # 左右の仕掛け: s=-1 は左（k<0）、s=+1 は右（k>1）。トーチの列はピストンの真裏（室内側 n=2）
    for side, piston_k in ((-1, -2), (+1, 3)):
        put(piston_k, 2, U, S)                               # トーチの台（床下の配線で通電 → トーチが消える）
        put(piston_k, 2, F, "redstone_torch[lit=true]")      # 常時オン。床の中に埋まる
        put(piston_k, 2, F + 1, S)                           # トーチで強く通電 → 隣の下のピストン
        put(piston_k, 2, F + 2,                              # 十字の粉 → 隣の上のピストン（石レンガに囲まれて見えない）
            "redstone_wire[east=side,west=side,north=side,south=side,power=15]")
        for y in range(F + 1, F + 4):
            put(piston_k, 3, y, S)                           # 粉の室内側のふた
        used.add(at(piston_k, 3))
        for y in (F + 1, F + 2):
            put(piston_k, 1, y, "air")                       # ピストンと頭と扉は最後に順番どおり置く
            put(piston_k - side, 1, y, "air")
            put(piston_k - 2 * side, 1, y, "air")
        facing = {(0, -1): "north", (0, 1): "south", (-1, 0): "west", (1, 0): "east"}[(-side * wx, -side * wz)]
        for y in (F + 1, F + 2):
            px, pz = at(piston_k - side, 1)                  # 縮んだ状態でガラスが張り付く所
            c.B.ordered.append((px, y, pz, P["door_glass"]))
        for y in (F + 1, F + 2):
            px, pz = at(piston_k, 1)
            c.B.ordered.append((px, y, pz, f"sticky_piston[facing={facing},extended=false]"))  # 置くと通電で伸びる
    # 床下の配線: 感圧板の下（外 n=0・室内 n=2）と扉の下をつなぎ、左右のトーチの台へ
    wire = "redstone_wire[east=side,west=side,north=side,south=side,power=0]"
    for k in (0, 1):
        for n in (0, 1, 2):
            put(k, n, U, wire)
        put(k, 0, F + 1, P["door_plate"])
        put(k, 2, F + 1, P["door_plate"])
        put(k, 0, F, P["porch_floor"])
        put(k, 2, F, P["floor"])
    for k in (-1, 2):                         # トーチの台へ（室内側の列、床下）
        put(k, 2, U, wire)
    for k in range(-1, 3):
        for n in (0, 1, 2):
            used.add(at(k, n))
    return used


# ---------------- 部位の辞書（.claude/skills/building-remodel/recipes.md）の部品 ----------------

def _name(s):
    return s.split("[")[0].split("{")[0].replace("minecraft:", "")


def _family(name):
    """つながる形のブロックの種類（柵・塀・板ガラス/鉄格子）。それ以外は None。"""
    if name.endswith("_fence") and "gate" not in name:
        return "fence"
    if name.endswith("_wall") and "sign" not in name and "banner" not in name:
        return "wall"
    if name.endswith("glass_pane") or name.endswith("_bars") or name == "iron_bars":
        return "pane"
    return None


_SOLIDISH = ("_slab", "_stairs", "air", "lantern", "chain", "banner", "torch", "button", "pressure_plate",
             "carpet", "trapdoor", "door", "sign", "flower", "leaves", "glass_pane", "_bars", "_fence", "_wall")


def connect(B):
    """柵・塀・板ガラス・鉄格子の「つながり」を、まわりのブロックから決め直す。
    setblock は置いた順で形が決まり、後から隣に置いても前の形のままになることがあるため（横棒が途切れる）。"""
    dirs = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
    for (x, y, z), s in list(B.items()):
        n = _name(s)
        fam = _family(n)
        if not fam:
            continue
        props = []
        for d, (dx, dz) in dirs.items():
            t = B.get((x + dx, y, z + dz))
            ok = False
            if t:
                tn = _name(t)
                ok = _family(tn) == fam or (_family(tn) is None and not any(w in tn for w in _SOLIDISH))
            if fam == "wall":
                props.append(f"{d}={'low' if ok else 'none'}")
            else:
                props.append(f"{d}={'true' if ok else 'false'}")
        if fam == "wall":
            props.append("up=true")
        B[(x, y, z)] = f"minecraft:{n}[{','.join(props)}]" if s.startswith("minecraft:") else f"{n}[{','.join(props)}]"


def planter_ring(c, select, edge="brick_wall", fill="diorite"):
    """植え込み: 建物の壁に沿わせる。壁のすぐ外の1マスに砂利（fill）、その外側を細いレンガの塀（edge）で囲う。
    select(セル) が真の「壁のすぐ外のセル」が砂利になる。端も塀で閉じる。高さは1マス。
    壁から離して歩道の上に置かない（植え込みは建物の足元にある）。戻り値: (砂利のセル, 塀のセル)"""
    ring1 = ring_of(c.bld)
    gravel = {p for p in ring1 if p in c.site and select(p)}
    edge_cells = {(x + dx, z + dz) for (x, z) in gravel for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
    edge_cells = {p for p in edge_cells - gravel - c.bld if p in c.site}
    for (x, z) in gravel:
        c.put(x, c.G + 1, z, fill)
    for (x, z) in edge_cells:
        c.put(x, c.G + 1, z, edge)
    return gravel, edge_cells


def eave_slab(c, slab="mangrove_slab", lantern_every=4, faces=None):
    """帯（軒）: 壁から1マス張り出した **ハーフブロック**（下付き）。フルブロックにしない（帯は薄い）。
    軒下に吊りランタンを lantern_every マスおき（faces の面だけ。看板などが既にある所は置かない）。
    赤いコンクリートにハーフは無いので、赤系のハーフ（mangrove_slab 等）を使う。"""
    for (x, z) in c.ring:
        c.put(x, c.top, z, f"{slab}[type=bottom]")
    if not lantern_every:
        return
    for (x, z), dirs in outline(c.roof).items():
        for d in dirs:
            if faces and d not in faces:
                continue
            if (z if d in ("w", "e") else x) % lantern_every:
                continue
            p = (x + STEP[d][0], c.top - 1, z + STEP[d][1])
            if p not in c.B:
                c.put(*p, "lantern[hanging=true]")


def lattice(c, height=3, bars="nether_brick_fence", skip=()):
    """屋上の格子: 屋根の縁（壁の真上）に柵を height 段積む。柵は横につながって横棒になり、向こうが透ける。"""
    for (x, z) in outline(c.roof):
        if (x, z) in skip:
            continue
        for i in range(1, height + 1):
            c.put(x, c.top + i, z, bars)


def box_on_roof(c, cells, height, material):
    """屋上に載る箱（看板の塔など）。cells の上に height 段。"""
    for (x, z) in cells:
        for i in range(1, height + 1):
            c.put(x, c.top + i, z, material)


def bollard(c, spots, y, post="polished_blackstone_wall", light="lantern"):
    """車止め・足元灯: 黒い塀のブロックの上にランタン（辞書の「柱の上の明かり・車止め」。y は塀の段）。"""
    for (x, z) in spots:
        c.put(x, y, z, post)
        c.put(x, y + 1, z, light)