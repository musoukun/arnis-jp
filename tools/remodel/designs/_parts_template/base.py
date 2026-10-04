"""
約束（親が書く。パーツを書く Agent はここを読むだけで、書き換えない）。★ を写真と質問の答えで埋める。
<建物名>（OSM way <番号>）／写真: <パス>
"""

import parts

WAY = 0                       # ★ OSM の建物の way 番号
EXCLUDE = []                  # ★ 敷地に入れない隣の建物の way 番号
PHOTO = r""                   # ★ 写真のパス

STACK = ["glass", "glass", "glass", "glass", "frame"]   # 土台（地面+1）の上に積む段。最後の段は帯の段（c.top）と重なる（店舗は5段のまま）
ROOF = {"type": "flat"}       # ★ 法則4
WINDOW_FACES = {"w"}          # ★ 窓のある面（入口の面）。ほかの面の一部だけの窓はパーツで parts.window_strip
PILLAR_EVERY = 99
DOOR_FACE = None              # 入口は組み立て役が front_entrance で作る
PLINTH = 1
PAL = {}                      # ★ 既定（parts.DEFAULT_PAL）と違う素材だけ
BAND = "mangrove_slab"        # ★ 帯（ハーフ）のブロック

SHAPE = dict(shift=(0, 0), grow={}, straighten=())          # ★ 建物の形（法則1・質問の答え）
ENTRANCE = dict(face="w", door_k=10, left_gap=3, right_gap=1, bed_end=6)   # ★ 入口（質問の答え）


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
    """プレビューのカメラ（座標を書かない）。写真の視点（斜め）・入口の正面・横の面。"""
    e = ENTRANCE
    f = parts.Facade(c, e["face"])
    return {
        "street": parts.camera(c, e["face"], -6, 8, look_k=f.width // 2),   # ★ 写真の視点
        "front": parts.camera(c, e["face"], e["door_k"], 10),
        "side": parts.camera(c, "n", 4, 8),                                  # ★ 横の面
    }


def sections(c):
    """施工の前に見る断面。入口の中心は必ず入れる。"""
    e = ENTRANCE
    x, z = parts.Facade(c, e["face"]).line(e["door_k"], 0)
    return [("扉の中心", "z", z) if e["face"] in ("w", "e") else ("扉の中心", "x", x)]
