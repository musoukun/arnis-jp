"""
ケンタッキーフライドチキン 堺北花田店（OSM way 389051876）の別案（sub）。
kfc_kitahanada.py をそのまま写し、**北面だけ** kfc_test.py（スキルのテストで書かれた設計）の作りに合わせた物。
ユーザーの評価（2026-10-04）: 北面の作りは kfc_test.py の方が良い。北面以外は kfc_kitahanada.py のまま。
北面で kfc_test.py に合わせた所（見た目を丸ごと。座標は建物の形 Anchor から求める）:
  - 窓: 北西の角から NORTH_GLASS = 5 マス（角の柱を含む）。窓は3段（F+1〜F+3）で1マス奥に引っ込め、
        角から2マス目に黒い板ガラスの細い縦枠（壁の線）。残りは明るい灰色の壁（smooth_stone）。
  - 柱と帯の下の段: 北面の角の柱（北西・北東）は polished_blackstone（テストの frame）。北面の壁の F+4 も同じ黒い段。
        北西の角の柱は西面と共通なので、西の正面から見ても北端の1列が黒くなる。
  - 途中の段差（建物の形の1マスの段差）は柱にせず、壁と同じ作り（灰色の壁＋黒い段）にして目立たなくする。
  - 土台（F の段）: 窓と角の柱の下は polished_deepslate、窓の無い壁の下は polished_andesite（テストと同じ）。
  - 「11」の看板（eleven）: 5×3、北面の窓の無い壁の真ん中に、低く（F+1〜F+3。テストの poster_n と同じ高さ）。
  - ドライブスルーの看板（drive）: 3×2、北向き。細い足1本で、植え込みが北から西へ曲がる角のマス（北西の角の斜め外）に立つ。
    植え込みの外の縁とのすき間は無い（ユーザー 2026-10-04「一番角にある」「細い足」）。絵はテストの物。
  - 室内: 北面の窓の奥、角から3マス目に「椅子・机・椅子」（テストの北面の窓から見える家具と同じ並び）。
          引っ込めたガラスの列（北の壁の1マス内側）には、西の窓の机・椅子・吊りランタンを置かない（ガラスと重なるため）。
  - 北面の車止めのうち、「11」の看板の真下に来る2本は置かない（看板の額縁と重なるため）。
お手本: .claude/skills/image2mc-builder/examples/kfc_kitahanada/reference.webp（実物の写真を Minecraft のブロックで描き起こした見本）。
正解: 同じフォルダの answer.json（kfc_kitahanada.py の正解。この別案は北面だけ違う）。

寸法表（お手本を見て、隣のフルブロックと人の体（1.8マス）と比べて決めた。画素は測らない）:
  部位            幅×高さ×奥行き / 形                              位置（建物の形からの相対）
  1階の壁         地面〜帯の下 5マス                               全周
  帯（軒）        厚さ 0.5（ハーフ）、壁から1マス張り出し           壁の上端。全周
  北西の塔        幅5（北面に沿って）×高さ4×奥行き2                北西の角。看板は北向き
  西の塔          幅5（西面に沿って）×高さ4×奥行き2                入口の真上（入口が塔の中央）。看板は西向き
  西の塔の南の段  幅1×高さ3×奥行き2                                西の塔の南隣
  屋上の格子      ネザーレンガの柵 3段（横棒が透ける）              屋根の縁。塔の所以外
  ロゴの看板      3×3（枠込み）、壁から1マス飛び出す、上端は塔より1マス上  各塔の「KFC」の上
  「KFC」の文字   幅5×高さ2（塔の幅いっぱい）                      各塔の下2段
  ドライブスルー  3×2、北向き、足2本（kfc_test.py に合わせた）      北西の角の西、角から2マス南
  「11」の看板    5×3、北の壁に平らに、低く（F+1〜F+3）             北面の窓の無い壁の真ん中（kfc_test.py に合わせた）
  店先の窓        板ガラス 高さ4、3マスおきに黒い細い縦枠（太い柱は角と入口の脇だけ）  西面
  北面の窓        板ガラス 高さ3（1マス奥）、角から2マス目に黒い細い縦枠  北西の角から5マス（kfc_test.py に合わせた）
  北面の柱と段    polished_blackstone の角の柱と F+4 の段、土台 polished_deepslate  北面（kfc_test.py に合わせた）
  植え込み        壁のすぐ外に砂利1マス＋その外に細いレンガの塀、高さ1   北面と西面の足元（入口の前は空ける）
  車止め          黒い塀のブロック1つ                              砂利の上、3マスおき
  入口の段        ハーフ1枚                                        入口の前
"""

import parts
from parcel import cells_in

G = -62  # run.py がワールドの地面を測って上書きする
WAY = 389051876
LANDUSE = 1052342556
EXCLUDE = [389051949]     # ガスト（施工済み。敷地に入れない）

STACK = ["glass", "glass", "glass", "glass", "frame"]   # 土台1 ＋ 窓4段 = 地面から5マス。その上の段に帯（ハーフ）
ROOF = {"type": "flat"}
WINDOW_FACES = {"w"}
PILLAR_EVERY = 99                        # 窓の途中に太い柱は入れない（お手本は大きなガラス面）。細い縦枠は extras で
DOOR_FACE = None
PLINTH = 1
PAL = {
    "plain_wall": "smooth_stone",        # 窓の無い壁（明るい灰色）
    "frame": "deepslate_bricks",         # 柱と塔（灰色のレンガ）
    "glass": "glass_pane",               # 板ガラス
    "roof_flat": "deepslate_bricks",
    "parapet": "nether_brick_fence",
    "plinth": "polished_andesite",
    "porch_floor": "cut_sandstone",
}
BAND = "mangrove_slab"                   # 赤い帯はハーフ。赤いコンクリートにハーフは無いので、赤系の木のハーフ
TOWER = "deepslate_bricks"

# 入口のまわり（ユーザーの答え 2026-10-04: 扉と塔は正面の真ん中から南へ2マス、左の通路は衝立から植え込み2マス、右は4マス）
DOOR_FROM_MIDDLE = 2                     # 扉（2マス）の中心は、正面の真ん中から南へ何マスか
GAP_LEFT, GAP_RIGHT = 3, 1               # 衝立と左右の通路のあいだの植え込みの幅（ユーザーの手直し 2026-10-04: 右の通路は衝立の1マス南）
BED_END = 6                              # 植え込みと通り道の南の端（衝立の南の端から何マス先を塀で閉じるか。ユーザーの手直し）

# 北面（kfc_test.py の北面に合わせる）
NORTH_GLASS = 5                          # 北面の窓は北西の角から5マス（角の柱を含む。テストの答え8）
NORTH_MULLION = 2                        # 細い縦枠は北西の角から2マス目（テストの北面と同じ並び）
NORTH_GLASS_ROWS = 3                     # 北面の窓は3段（F+1〜F+3）。その上の F+4 が帯の下の暗い段
NORTH_FRAME = "polished_blackstone"      # 北面の角の柱と帯の下の暗い段（テストの frame の色）
NORTH_PLINTH = "polished_deepslate"      # 北面の窓と角の柱の下の土台（テストの plinth）
NORTH_SEATS = 3                          # 北面の窓の奥の「椅子・机・椅子」は北西の角から3マス目（テストと同じ並び）
# 北面をテストとマスごとに突き合わせて合わせた所（2026-10-04、ユーザー「北面はテストの方が良い」）
NORTH_SIGN = (9, 13)                     # 「11」の看板は北西の角から 9〜13 マス目（テストの poster_n と同じ）
NORTH_BOLLARDS = (2, 6, 10, 14)          # 北面の車止めは北西の角から 2・6・10・14 マス目、ランタン無し（テストと同じ）
NORTH_LANTERNS = (3, 7, 11, 15)          # 北面の軒下の吊りランタンは北西の角から 3・7・11・15 マス目（テストと同じ）
DRIVE_K = -1                             # ドライブスルーの看板の足は、植え込みが北から西へ曲がる角のマス（北西の角の斜め外。ユーザー 2026-10-04）
NE_FENCE = (-2, 1)                       # 北東の角の 2 マス手前〜1 マス先に、植え込みの外の縁としてネザーレンガの柵 2 段（テストの答え11）


# 建物の大きさ（ユーザー 2026-10-04: ワールドが1.3〜1.4倍なので、比率に合わせて数マス大きく。正面の前に植え込みと通り道の余裕を作る）
SHIFT_E = 2                              # 東へずらす（正面の前を 4 → 6 マスに）
SHIFT_S = 6                              # 南へずらす（ユーザー 2026-10-04: 北面の前にドライブスルーの通り道を空ける。南のガストまで8マス残る）
EXT_N, EXT_S = 2, 1                      # 正面の幅を北と南へ広げる（まわりの余白: 北 約7、南 約5）


def footprint(geo):
    base = {(x + SHIFT_E, z + SHIFT_S) for (x, z) in cells_in(geo.polygon(WAY))}
    bld = set(base)
    for x in {x for x, _ in base}:
        zs = [z for xx, z in base if xx == x]
        bld |= {(x, min(zs) - k) for k in range(1, EXT_N + 1)}
        bld |= {(x, max(zs) + k) for k in range(1, EXT_S + 1)}
    # 北面を1本のまっすぐな壁にする（テストの北面と同じ。ユーザー指摘 2026-10-04「真っすぐじゃない」）。
    # 北の端から2マス以内の段は、北の端までそろえる（北東の角の大きな切り欠きはそのまま）
    zn = min(z for _, z in bld)
    for x in {x for x, _ in bld}:
        top = min(z for xx, z in bld if xx == x)
        if top - zn <= 2:
            bld |= {(x, z) for z in range(zn, top)}
    return bld, set(bld)


def site_cells(geo):
    bld, roof = footprint(geo)
    around = {(x + dx, z + dz) for (x, z) in roof for dx in range(-7, 8) for dz in range(-7, 8)}
    excluded = set().union(*(cells_in(geo.polygon(w)) for w in EXCLUDE))
    return {(x, z) for (x, z) in around if x >= 585 and (x, z) not in excluded}


class Anchor:
    """建物の形から決まる基準（座標を直に書かない）。"""

    def __init__(self, bld):
        self.bld = bld
        self.x0 = min(x for x, _ in bld)                               # 西の壁
        self.zn = min(z for x, z in bld if x == self.x0)               # 北西の角の z
        self.x1 = max(x for x, _ in bld)
        zs = [z for x, z in bld if x == self.x0 or (x - 1, z) not in bld and x <= self.x0 + 1]
        face = max(zs) - self.zn + 1                                      # 正面（西の面）の長さ
        left = self.zn + face // 2 + DOOR_FROM_MIDDLE - 1
        self.door = [left, left + 1]                                      # 入口の z（2マス）
        self.wx = min(x for x, z in bld if z == self.door[0])          # 入口の所の西の壁の x
        self.top = G + PLINTH + len(STACK)                             # 帯の段

    def tower_nw(self):   # 幅5（x）× 奥行き2（z）
        return {(x, z) for (x, z) in self.bld if self.x0 <= x <= self.x0 + 4 and self.zn <= z <= self.zn + 1}

    def tower_w(self):    # 幅5（z、入口が中央）× 奥行き2（x）。南側は壁が1マス奥でも、塔の正面はそろえる
        z0 = self.door[0] - 1
        return {(x, z) for x in (self.wx, self.wx + 1) for z in range(z0, z0 + 5)}

    def step_w(self):     # 西の塔の南隣の、1段低い所
        z = self.door[0] + 4
        return {(x, z) for x in (self.wx, self.wx + 1)}

    def screen(self):     # 扉の前の衝立（塀・ポスター・塀）。通り道の1マス外
        return [(self.wx - 2, z) for z in range(self.door[0] - 1, self.door[1] + 2)]

    def passages(self):   # 左右の通路（歩道から通り道へ）
        zs = [z for _, z in self.screen()]
        return min(zs) - GAP_LEFT - 1, max(zs) + GAP_RIGHT + 1

    def north_edge(self):
        """北面の壁の線（北に面したセル）。両端が角の柱。東の奥の段差（z が北西の角より南の所）は入れない。"""
        return sorted((x, z) for (x, z) in self.bld if (x, z - 1) not in self.bld and z <= self.zn)

    def north_corners(self):  # 北面の両端（北西・北東の角の柱）
        edge = self.north_edge()
        return [edge[0], edge[-1]]

    def north_face(self):
        """北面の壁のセル（角の柱を除く）。途中の1マスの段差も壁として入れる（テストの北面のように柱にしない）。"""
        return [p for p in self.north_edge() if p not in self.north_corners()]

    def north_glass(self):     # 北面の窓のセル（角の柱の東、角から NORTH_GLASS マスまで）
        return [(x, z) for (x, z) in self.north_face() if x < self.x0 + NORTH_GLASS]

    def eleven(self):
        """「11」の看板の左上の額縁 (x, z)。北面の窓の無い壁の真ん中（テストの poster_n と同じ決め方）。
        北向きの看板は列が西へ進むので、左上は真ん中の2マス東。額縁は壁の1マス外。"""
        wall_z = {x: z for (x, z) in self.north_face()}
        k0, k1 = NORTH_SIGN
        assert len({wall_z[self.x0 + k] for k in range(k0, k1 + 1)}) == 1, "看板の5マスが同じ壁の面に乗っていない"
        return self.x0 + k1, wall_z[self.x0 + k1] - 1


def sections(geo):
    """施工の前に見る断面 (名前, 軸, 値)。run.py section で AA にして、お手本と見比べる。"""
    a = Anchor(footprint(geo)[0])
    return [("扉の中心", "z", a.door[0]), ("衝立の端", "z", a.door[0] - 1), ("左の通路", "z", a.passages()[0]),
            ("自動扉の仕掛け（左）", "z", a.door[0] - 2)]


def signs(geo):
    """(名前, 列, 行, 左上の額縁, 向き)。列は正面から見て左→右。"""
    a = Anchor(footprint(geo)[0])
    top, z0 = a.top, a.door[0] - 1
    ex, ez = a.eleven()
    return [
        ("kfc_n", 5, 2, (a.x0 + 4, top + 2, a.zn - 1), "north"),        # 北西の塔の「KFC」（壁に直接）
        ("logo_n", 3, 3, (a.x0 + 3, top + 5, a.zn - 2), "north"),       # その上のロゴ（1マス飛び出す）
        ("kfc_w", 5, 2, (a.wx - 1, top + 2, z0), "west"),               # 西の塔の「KFC」
        ("logo_w", 3, 3, (a.wx - 2, top + 5, z0 + 1), "west"),
        ("eleven", 5, 3, (ex, G + PLINTH + 3, ez), "north"),            # 北の壁の黒い看板（窓の無い壁の真ん中、F+1〜F+3。テストの poster_n）
        ("drive", 3, 2, (a.x0 + DRIVE_K + 1, top - 1, a.zn - 2), "north"),  # ドライブスルー（北向き。板の真ん中が足の真上、上は軒の真下、額縁は植え込みの外の縁の上）
        ("poster", 2, 3, (a.wx - 3, G + 4, a.door[0]), "west"),         # 扉の前の衝立のポスター（植え込みの上。塀で囲う）
    ]


SIGN_BACKING = {
    "kfc_n": None, "kfc_w": None,                     # 壁に直接（文字の背景は透明）
    "poster": "deepslate_bricks",                     # 衝立の芯
    "logo_n": "black_concrete", "logo_w": "black_concrete",
    "eleven": "black_concrete", "drive": "black_concrete",
}


def sign_images():
    from PIL import Image, ImageDraw, ImageFont
    import map_art as M
    S = M.SIZE
    W, R, K = (255, 255, 255, 255), (200, 25, 30, 255), (18, 18, 18, 255)
    font = lambda px: ImageFont.truetype(M.FONT_BOLD, px)

    def centered(d, box, text, fill, px):
        x0, y0, x1, y1 = box
        f = font(px)
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        d.text(((x0 + x1 - (r - l)) / 2 - l, (y0 + y1 - (b - t)) / 2 - t), text, fill=fill, font=f)

    imgs = {}
    kfc = M.text_image([("KFC", W, 0.92)], 5, 2, bg=(0, 0, 0, 0))
    imgs["kfc_n"] = imgs["kfc_w"] = kfc

    logo = Image.new("RGBA", (3 * S, 3 * S), W)                    # 赤い枠の中に、白地に黒の顔
    d = ImageDraw.Draw(logo)
    w = logo.width
    d.rectangle((0, 0, w - 1, w - 1), outline=R, width=44)
    d.rectangle((44, w * 0.72, w - 44, w - 44), fill=R)
    d.ellipse((w * 0.33, w * 0.16, w * 0.67, w * 0.56), outline=K, width=12)            # 顔
    d.arc((w * 0.30, w * 0.10, w * 0.70, w * 0.40), 180, 360, fill=K, width=16)          # 髪
    d.line((w * 0.38, w * 0.33, w * 0.62, w * 0.33), fill=K, width=10)                   # 眼鏡
    d.polygon([(w * 0.46, w * 0.50), (w * 0.54, w * 0.50), (w * 0.50, w * 0.62)], fill=K)  # あごひげ
    d.polygon([(w * 0.40, w * 0.62), (w * 0.60, w * 0.70), (w * 0.60, w * 0.62), (w * 0.40, w * 0.70)], fill=K)  # 蝶ネクタイ
    imgs["logo_n"] = imgs["logo_w"] = logo

    el = Image.new("RGBA", (5 * S, 3 * S), K)
    d = ImageDraw.Draw(el)
    d.ellipse((S * 0.25, S * 0.5, S * 2.05, S * 2.5), outline=W, width=12)
    centered(d, (S * 0.25, S * 0.5, S * 2.05, S * 2.5), "11", W, int(S * 1.0))
    centered(d, (S * 2.1, S * 0.7, S * 4.9, S * 1.5), "it's finger", W, int(S * 0.5))
    centered(d, (S * 2.1, S * 1.5, S * 4.9, S * 2.3), "lickin' good", W, int(S * 0.5))
    imgs["eleven"] = el

    # ドライブスルー 3×2（kfc_test.py の _drive と同じ絵。北面の見た目をテストに合わせる）
    dr = Image.new("RGBA", (3 * S, 2 * S), R)
    d = ImageDraw.Draw(dr)
    u = S / 128
    d.rectangle((96 * u, 0, 3 * S, 96 * u), fill=K)
    d.text((240 * u, 48 * u), "ドライブスルー", font=font(int(40 * u)), fill=W, anchor="mm")
    d.polygon([(130 * u, 176 * u), (190 * u, 126 * u), (190 * u, 156 * u), (350 * u, 156 * u),
               (350 * u, 196 * u), (190 * u, 196 * u), (190 * u, 226 * u)], fill=W)       # 矢印（左向き）
    d.rectangle((0, 0, 92 * u, 2 * S), fill=K)
    for i, s in enumerate(("P", "24H", "IN")):
        d.text((46 * u, (45 + i * 80) * u), s, font=font(int((44 if i else 64) * u)), fill=W, anchor="mm")
    imgs["drive"] = dr

    po = Image.new("RGBA", (2 * S, 3 * S), (120, 190, 235, 255))
    d = ImageDraw.Draw(po)
    d.rectangle((0, 0, 2 * S, S * 0.4), fill=(235, 235, 230, 255))
    d.ellipse((S * 0.3, S * 1.2, S * 1.7, S * 2.3), fill=(215, 140, 50, 255))
    d.ellipse((S * 0.5, S * 1.8, S * 1.9, S * 2.8), fill=(190, 95, 40, 255))
    imgs["poster"] = po
    return imgs


CAMERAS = {
    "street": dict(rel_pos=(579.0, 1 + 1.7, 612.0), yaw=-40.0, pitch=2.0, vfov=57, width=930, height=612),  # 写真の視点
    "ref": dict(rel_pos=(580.5, 1 + 1.6, 613.5), yaw=-42.0, pitch=-8.0, vfov=70, width=1100, height=720),   # お手本の視点
    "front": dict(rel_pos=(578.5, 1 + 1.6, 635.5), yaw=-90.0, pitch=-8.0, width=1000, height=560),         # 入口の正面
    "north": dict(rel_pos=(593.0, 1 + 1.6, 617.5), yaw=0.0, pitch=-10.0, width=1000, height=560),          # 北面（植え込みと看板）
    "west": dict(rel_pos=(583.5, 1 + 1.6, 628.0), yaw=-90.0, pitch=-10.0, width=1000, height=560),         # 西面の北寄り（窓と植え込み）
}


def extras(c):
    G, F, top, P = c.G, c.F, c.top, c.pal
    a = Anchor(c.bld)

    # 塔: 幅5×高さ4×奥行き2。西の塔の南隣は1段低い（高さ3）
    t_nw, t_w, t_step = a.tower_nw(), a.tower_w(), a.step_w()
    parts.box_on_roof(c, t_nw, 4, TOWER)
    parts.box_on_roof(c, t_w, 4, TOWER)
    parts.box_on_roof(c, t_step, 3, TOWER)

    # 帯: 壁から1マス張り出したハーフ。西と北の軒下に吊りランタン
    parts.eave_slab(c, BAND, lantern_every=4, faces={"n", "w"})

    # 屋上の格子: ネザーレンガの柵を3段。塔の所は除く
    parts.lattice(c, 3, "nether_brick_fence", skip=t_nw | t_w | t_step)

    # 植え込み: 壁のすぐ外に砂利、その外に細いレンガの塀。北面と、西面の左の通路より北
    door0, door1 = a.door
    pass_l, pass_r = a.passages()

    def planted(p):
        x, z = p
        north = (x, z + 1) in c.bld and x <= a.x1 - 2
        west = (x + 1, z) in c.bld and z < pass_l          # 左の通路より北だけ壁沿い（そこから南は通り道）
        corner = (x + 1, z + 1) in c.bld and (x + 1, z) not in c.bld and (x, z + 1) not in c.bld and x < a.x0
        return north or west or corner
    gravel, _ = parts.planter_ring(c, planted, edge="brick_wall", fill="diorite")

    # 入口のまわり（手前から奥へ: 植え込み・衝立 → 通り道 → 扉）。通り道は壁の1マス外（x = wx-1）
    walk_x, front_x = a.wx - 1, a.wx - 2
    scr = a.screen()
    scr_z = [z for _, z in scr]
    end_z = max(scr_z) + BED_END - 1                         # 植え込みと通り道の南の端（その1つ先を塀で閉じる）
    for z in range(pass_l, end_z + 1):                       # 通り道（壁の1マス外）
        for x in range(walk_x, a.x1):
            if (x, z) in c.bld:
                break
            for y in range(G + 2, G + 5):
                c.put(x, y, z, "air")
            c.put(x, G + 1, z, "brick_slab[type=bottom]")   # 床はレンガのハーフ（歩道よりハーフ高い）
    def bed(z0, z1):                                         # 衝立の前の植え込み: 塀・砂利・塀
        cells = [(front_x - 1, z) for z in range(z0, z1 + 1)]
        for (x, z) in cells:
            c.put(x, G + 1, z, "diorite")
            c.put(x - 1, G + 1, z, "brick_wall")
            if z not in scr_z:                               # 衝立の所は、衝立が奥の縁になる
                c.put(x + 1, G + 1, z, "brick_wall")
        for z in (z0, z1):                                   # 両端も塀で閉じる（囲いきる）
            for dx in (-1, 0, 1):
                c.put(front_x - 1 + dx, G + 1, z, "brick_wall")
        return [p for p in cells if p[1] not in (z0, z1)]
    beds = bed(pass_l + 1, end_z + 1)                        # 左の通路の南から、南の端の塀まで
    for x in range(front_x, a.wx + 1):                       # 南の端は建物まで塀で閉じる（通り道もそこで終わる）
        c.put(x, G + 1, end_z + 1, "brick_wall")
        for y in range(G + 2, G + 5):
            c.put(x, y, end_z + 1, "air")
    for z in (pass_l, pass_r):                               # 左右の通路（歩道から通り道まで）。植え込みを切って通す（端は塀で閉じない）
        for x in range(a.wx - 4, walk_x):
            for y in range(G + 2, G + 5):
                c.put(x, y, z, "air")
            c.put(x, G + 1, z, "brick_slab[type=bottom]")
    # 衝立: 植え込みの高さ（G+1）を台にして、その上にポスター（G+2〜G+4）。両端と上は深層岩レンガの塀で、上は帯の真下まで
    for (x, z) in scr:
        edge = z in (min(scr_z), max(scr_z))
        if edge:
            for y in range(G + 1, top):
                c.put(x, y, z, "deepslate_brick_wall")
        else:
            c.put(x, G + 1, z, "deepslate_bricks")
            c.put(x, top - 1, z, "deepslate_brick_wall")

    # 窓の細い縦枠: 3マスおきに黒い板ガラス（太い柱にしない）
    for (x, z), dirs in c.wall.items():
        if "w" in dirs and z % 3 == 0:
            for y in range(F + 1, F + 5):
                if c.B.get((x + 1, y, z)) == P["glass"]:
                    c.put(x + 1, y, z, "black_stained_glass_pane")

    # 北面（kfc_test.py の北面の見た目に合わせる）
    #   角の柱（北西・北東）: 黒い柱（F+1〜F+4）、土台は暗い石。北西の角の柱は西面と共通（西の正面の北端も黒くなる）
    #   窓: 北西の角から5マス（3段、1マス奥）、角から2マス目に黒い細い縦枠（壁の線）、土台は暗い石
    #   窓の無い壁: 灰色の壁のまま（途中の段差の柱も壁に戻して目立たなくする）、土台は明るい石
    #   帯の下の暗い段: 北面の壁の F+4 を全部黒い段に
    north_glass = a.north_glass()
    for (x, z) in a.north_corners():
        c.put(x, F, z, NORTH_PLINTH)
        for y in range(F + 1, F + NORTH_GLASS_ROWS + 2):
            c.put(x, y, z, NORTH_FRAME)
    for (x, z) in a.north_face():
        c.put(x, F + NORTH_GLASS_ROWS + 1, z, NORTH_FRAME)
        for y in range(F + 1, F + NORTH_GLASS_ROWS + 1):
            if c.B.get((x, y, z)) == P["frame"]:             # 途中の段差の柱 → 壁（看板の裏はそのまま）
                c.put(x, y, z, P["plain_wall"])
    for (x, z) in north_glass:
        c.put(x, F, z, NORTH_PLINTH)
        for y in range(F + 1, F + NORTH_GLASS_ROWS + 1):
            if x == a.x0 + NORTH_MULLION:
                c.put(x, y, z, "black_stained_glass_pane")
            else:
                c.put(x, y, z, "air")                        # 外側に凹み（帯の下の暗い段の下に影）
                c.put(x, y, z + 1, P["glass"])

    # ドライブスルーの看板の足（看板は signs の "drive"）: 細い柵1本。植え込みの角のマス（北と西の植え込みが合わさる所）の砂利から、板の裏まで
    for y in range(G + 2, c.top - 2):                           # 砂利の上から板の下まで
        c.put(a.x0 + DRIVE_K, y, a.zn - 1, "nether_brick_fence")

    # 車止め: 砂利の上に3マスおき（北面の前は除く。北面はテストと同じ位置にランタン無しで）
    parts.bollard(c, [(x, z) for (x, z) in gravel if (x + z) % 3 == 0 and (x, G + 2, z) not in c.B and z >= a.zn], G + 2)
    for k in NORTH_BOLLARDS:
        c.put(a.x0 + k, G + 2, a.zn - 1, "polished_blackstone_wall")
    # 北東の柵: 植え込みの外の縁（塀）の代わりに、ネザーレンガの柵を2段
    ne = a.north_corners()[1][0]
    for x in range(ne + NE_FENCE[0], ne + NE_FENCE[1] + 1):
        for y in (G + 1, G + 2):
            c.put(x, y, a.zn - 2, "nether_brick_fence")
    # 北面の軒下の吊りランタンを、テストと同じ位置に置き直す
    for (x, y, z), st in list(c.B.items()):
        if z == a.zn - 1 and y == top - 1 and st.startswith("lantern"):
            del c.B[(x, y, z)]
    for k in NORTH_LANTERNS:
        c.put(a.x0 + k, top - 1, a.zn - 1, "lantern[hanging=true]")
    # 衝立の前の植え込みの車止め（ユーザーの手直し 2026-10-04）: 衝立の両脇と、右の通路の南の植え込みの真ん中
    parts.bollard(c, [(front_x - 1, min(scr_z) - 1), (front_x - 1, max(scr_z) + 1),
                      (front_x - 1, (pass_r + end_z + 1) // 2)], G + 2, post="blackstone_wall")

    # 入口（最後に）: ハーフの段、通り道、柱に挟まれたガラスの自動扉、窓から見える室内
    door = [(a.wx, door0), (a.wx, door1)]
    parts.entrance(c, door, "w", height=3, out=1, steps="slab", step_slab="brick_slab")
    for (_, z) in door:                                      # 扉の前の1マスだけレンガのフルブロック（ユーザーの答え）
        c.put(walk_x, G + 1, z, "bricks")
    # 帯（軒）を衝立の上まで前に出して、通り道と衝立を覆う
    for z in range(pass_l, end_z + 2):                       # 左の通路から、南の端の塀の上まで
        for x in range(front_x, a.x1):
            if (x, z) in c.bld:
                break
            c.put(x, top, z, f"{BAND}[type=bottom]")
    used = parts.auto_door(c, door, "w")
    # 北面の窓の奥に引っ込めたガラスの列には、机・椅子・吊りランタンを置かない（ガラスを潰さない）
    north_recess = {(x, z + 1) for (x, z) in north_glass}
    parts.furnish(c, {"w"}, avoid=used | north_recess)
    # 北面の窓の奥の「椅子・机・椅子」（テストの北面の窓から見える家具と同じ並び。背もたれは壁側と奥側）
    sx = a.x0 + NORTH_SEATS
    c.put(sx, F + 1, a.zn + 2, f"{P['chair']}[facing=north,half=bottom]")
    c.put(sx, F + 1, a.zn + 3, P["table"])
    c.put(sx, F + 2, a.zn + 3, P["table_top"])
    c.put(sx, F + 1, a.zn + 4, f"{P['chair']}[facing=south,half=bottom]")
