"""
約束（親が書く。パーツを書く Agent はここを読むだけで、書き換えない）。
★ は全部、写真と手札（recipes.md の「手札」）と質問の答えで埋める。既定のまま残さない（None のままだと、その部位は作られない）。
<建物名>（OSM way <番号>）／写真: <パス>
"""

import parts

WAY = 0                       # ★ OSM の建物の way 番号
EXCLUDE = []                  # ★ 敷地に入れない隣の建物の way 番号
PHOTO = r""                   # ★ 写真のパス

STACK = []                    # ★ 壁の段（法則3 の表から。例 店舗 ["glass"]*4 + ["frame"]）。土台の上に積み、最後の段は帯の段（c.top）と重なる
ROOF = None                   # ★ 屋根（法則4。{"type": "flat"} / {"type": "hip", "rise": 2.5} / {"type": "gable", ...}）
WINDOW_FACES = set()          # ★ 面全体が窓の面（写っている面だけ）。面の一部だけの窓はパーツで parts.window_strip
PILLAR_EVERY = 3              # ★ 窓の太い柱の間隔（大きなガラス面なら 99 ＝ 角と入口の脇だけ）
DOOR_FACE = None              # 入口は ENTRANCE で作るので None のまま
PLINTH = 1                    # ★ 土台の段（足元にレンガ・石の帯や入口の段があれば 1。自動扉は 1 が要る）
PAL = {}                      # ★ 既定（parts.DEFAULT_PAL）と違う素材だけ（法則6・辞書）
BAND = None                   # ★ 帯（軒）のハーフのブロック。手札「帯・軒」で帯が無ければ None

SHAPE = dict(shift=(0, 0), grow={}, straighten=())   # ★ 建物の形（法則1・質問の答え・人の位置の指示）

# ★ 入口（recipes.md の「入口の型の選び方」で型を決め、位置は質問の答え）。左の角から door_k マス目に扉（2マス）
#   衝立つき: dict(kind="衝立つき", face="w", door_k=10, poster=True, auto=True, left_gap=3, right_gap=1, bed_end=6)
#   扉だけ  : dict(kind="扉だけ", face="s", door_k=4, steps="landing", auto=True)   steps は "landing" / "slab" / "stairs"
ENTRANCE = None


def footprint(geo):
    """建物の形: OSM を幅・奥行き 1.3 に縮め（building_cells）、SHAPE で整える。"""
    bld = parts.grow_footprint(parts.building_cells(geo, WAY), **SHAPE)
    return bld, set(bld)


def site_cells(geo):
    """敷地: 建物のまわり6マス（★ 歩道・道路の手前で切るなら条件を足す）。隣の建物は入れない。"""
    from parcel import cells_in
    bld, roof = footprint(geo)
    around = {(x + dx, z + dz) for (x, z) in roof for dx in range(-6, 7) for dz in range(-6, 7)}
    excluded = set().union(*(cells_in(geo.polygon(w)) for w in EXCLUDE)) if EXCLUDE else set()
    return around - excluded


def cameras(c):
    """プレビューのカメラ（座標を書かない）。★ 写真の視点（斜め）・入口の正面・横の面。"""
    face = ENTRANCE["face"] if ENTRANCE else "w"     # ★ 写真に写っている正面
    f = parts.Facade(c, face)
    cams = {"street": parts.camera(c, face, -6, 8, look_k=f.width // 2)}   # ★ 写真の視点
    if ENTRANCE:
        cams["front"] = parts.camera(c, face, ENTRANCE["door_k"], 10)
    return cams


def sections(c):
    """施工の前に見る断面。入口があれば、その中心は必ず入れる。"""
    if not ENTRANCE:
        return []
    x, z = parts.Facade(c, ENTRANCE["face"]).line(ENTRANCE["door_k"], 0)
    return [("扉の中心", "z", z) if ENTRANCE["face"] in ("w", "e") else ("扉の中心", "x", x)]
