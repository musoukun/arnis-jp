"""
パーツを集めて1つの建物に組み立てる（image2mc-builder の並列の作り方）。

建物ごとのフォルダ designs/<建物名>/ の中:
  base.py     … 約束（親が書く）: WAY・SHAPE・STACK・PAL・BAND・ENTRANCE・footprint(geo)・site_cells(geo)・cameras(c)・sections(c)
  plan.md     … 受け持ちの表（親が書く）: 部位表・高さの基準・面の長さ・質問の答え・だれがどのファイルを書くか
  p_<名前>.py  … パーツ（Agent が1つずつ並列に書く）。どれも同じ形:
                  ORDER = 20                 … 組み立ての順（小さいほど先。屋上 10、面 20、外まわり 30）
                  def part(c): ...           … ブロックを置く（無くてよい）
                  def signs(geo, c): ...     … 看板の一覧 [(名前, 列, 行, 左上の額縁, 向き)]（無くてよい）
                  BACKING = {名前: ブロック} … 看板の裏（無くてよい）
                  def images(): ...          … 看板の絵 {名前: PIL の画像}（無くてよい。sign_art の型で描く）
  __init__.py … 組み立て役（型のまま。書き換えない）

組み立て: パーツを ORDER の順に呼び、最後に入口（base.py の ENTRANCE）と室内（parts.furnish）を置く。
入口の型（ENTRANCE["kind"]。選び方は recipes.md の「入口の型の選び方」）:
  "衝立つき" … parts.front_entrance（衝立・通り道・植え込み・左右の通路・扉）。ENTRANCE["poster"] が真なら衝立にポスター
  "扉だけ"   … parts.entrance（壁の線の扉と段）。ENTRANCE["steps"] で段の作り
  どちらも ENTRANCE["auto"] が真ならガラスの自動扉。ENTRANCE = None なら入口を置かない（パーツで作る）
パーツだけを試す: 環境変数 REMODEL_ONLY=<名前>（p_ を除いた名前。カンマ区切りで複数）で、そのパーツだけを組み立てる
  例: REMODEL_ONLY=roof python run.py kfc_test7 preview p_roof
"""

import importlib.util
import os
import sys
from pathlib import Path

import parts


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def place_entrance(c, e, band):
    """入口を ENTRANCE の型で置く（最後に置くので、壁・窓・植え込みを上書きして通り道を空けられる）。戻り値は室内で避けるセル。"""
    if not e:
        return set()
    kind, auto = e.get("kind"), e.get("auto", True)
    if kind == "衝立つき":
        fe = parts.front_entrance(c, e["face"], e["door_k"], screen_k=e.get("screen_k"), screen_w=e.get("screen_w", 4),
                                  left_gap=e.get("left_gap", 3), right_gap=e.get("right_gap", 1),
                                  bed_end=e.get("bed_end", 6), band=band, auto=auto)
        return fe["used"]
    if kind == "扉だけ":
        f = parts.Facade(c, e["face"])
        door = [f.at(e["door_k"]), f.at(e["door_k"] + 1)]
        parts.entrance(c, door, e["face"], height=e.get("height", 3), steps=e.get("steps", "landing"))
        return parts.auto_door(c, door, e["face"]) if auto else set()
    raise ValueError(f"ENTRANCE の kind は \"衝立つき\" か \"扉だけ\"（今は {kind!r}）")


def assemble(ns, package):
    """designs/<建物名>/__init__.py から呼ぶ。base.py の中身とパーツを、run.py が読む設計の形にして ns に入れる。"""
    folder = Path(ns["__file__"]).parent
    base = _load(folder / "base.py", f"{package}.base")
    ns.update({k: v for k, v in vars(base).items() if not k.startswith("__")})
    only = {x.strip() for x in os.environ.get("REMODEL_ONLY", "").split(",") if x.strip()}
    pieces = []
    for f in sorted(folder.glob("p_*.py")):
        name = f.stem[2:]
        if only and name not in only:
            continue
        pieces.append((getattr(m := _load(f, f"{package}.{f.stem}"), "ORDER", 50), name, m))
    pieces.sort(key=lambda t: (t[0], t[1]))
    me = sys.modules[package]

    def _ctx(geo):
        return parts.Ctx(me, geo, 7)

    def signs(geo):
        c = _ctx(geo)
        out = []
        e = getattr(base, "ENTRANCE", None)
        if e and not only and e.get("kind") == "衝立つき" and e.get("poster"):
            out.append(parts.entrance_poster(c, e["face"], e["door_k"], e.get("screen_k"), e.get("screen_w", 4)))
        for _, _, m in pieces:
            if hasattr(m, "signs"):
                out += m.signs(geo, c)
        names = [s[0] for s in out]
        dup = {n for n in names if names.count(n) > 1}
        assert not dup, f"看板の名前がパーツどうしで重なっている: {dup}"
        return out

    def sign_images():
        imgs = dict(getattr(base, "IMAGES", {}))
        for _, _, m in pieces:
            if hasattr(m, "images"):
                imgs.update(m.images())
        e = getattr(base, "ENTRANCE", None)
        if e and not only and e.get("kind") == "衝立つき" and e.get("poster") and "poster" not in imgs:
            import sign_art
            print("注意: 衝立のポスターの絵（\"poster\"）を描くパーツがありません。無地で代わりにします（p_sign_poster.py の images() で描く）")
            imgs["poster"] = sign_art.shapes(2, 3, (200, 200, 200), [])
        return imgs

    backing = dict(getattr(base, "SIGN_BACKING", {"poster": "deepslate_bricks"}))
    for _, _, m in pieces:
        backing.update(getattr(m, "BACKING", {}))

    def extras(c):
        for _, name, m in pieces:
            if hasattr(m, "part"):
                m.part(c)
        if only:                                 # パーツだけを試す時は、入口と室内を置かない
            return
        used = place_entrance(c, getattr(base, "ENTRANCE", None), getattr(base, "BAND", None))
        faces = set(getattr(base, "WINDOW_FACES", set()))
        if faces:
            parts.furnish(c, faces, avoid=used)

    out = dict(signs=signs, sign_images=sign_images, SIGN_BACKING=backing, extras=extras, _ctx=_ctx,
               PARTS=[name for _, name, _ in pieces])
    if hasattr(base, "cameras"):                 # base.py の cameras(c)・sections(c) は、建物の情報 c を受け取る
        out["cameras"] = lambda geo: base.cameras(_ctx(geo))
    if hasattr(base, "sections"):
        out["sections"] = lambda geo: base.sections(_ctx(geo))
    ns.update(out)
