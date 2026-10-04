"""
設計ファイルを施工する入口（どの建物でも共通）。
  python run.py <設計名> preview [タグ]   … ワールドに置かず、写真と同じ視点の絵を out/ に描く
  python run.py <設計名> build ["メモ"]   … 施工（初回は敷地の控え baseline を自動で取る）＋看板の地図アート
  python run.py <設計名> reset           … 更地（baseline）に戻す（看板の額縁も消す）
  python run.py <設計名> section [x|z 値] … 横から見た断面の AA（無ければ設計の sections(geo) の断面）
  python run.py <設計名> check           … 施工の前の自動チェック（build の前にも必ず走る。警告があれば止まる）
<設計名> は designs/<設計名>.py。
"""

import importlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "designs"))

import checks
import parts
from builder import AIR, Construction, norm
from parcel import ROOT, OsmGeometry, cells_in
from render import VoxelScene, render_top, render_view
from world_reader import load_area

OUT = HERE / "out"  # プレビュー画像（git 管理外）
OUT.mkdir(exist_ok=True)
OSM_JSON = ROOT / "doc" / "kitahanada" / "osm_data.json"
# ユーザーの Minecraft の視野角（既定 102、ユーザーが指定したら view.json を書き換える）
VIEW = json.loads((HERE / "view.json").read_text(encoding="utf-8"))  # arnis が保存した OSM（範囲が違えば osm_cache の方）


def detect_ground(geo, spec, site) -> int:
    """建物から離れた敷地セルの「最上ブロックの Y」の最頻値 = 地面（地形で場所ごとに変わるので毎回測る）。"""
    bld = cells_in(geo.polygon(spec.WAY))
    around = {(x + dx, z + dz) for (x, z) in bld for dx in range(-3, 4) for dz in range(-3, 4)}
    probe = [c for c in site if c not in around]
    xs, zs = [c[0] for c in probe], [c[1] for c in probe]
    snap = load_area(min(xs), min(zs), max(xs), max(zs), y0=-64, y1=0)
    top = {}
    for (x, y, z) in snap.blocks:
        if (x, z) in probe and y > top.get((x, z), -999):
            top[(x, z)] = y
    return Counter(top.values()).most_common(1)[0][0]


def load(name: str):
    spec = importlib.import_module(name)
    geo = OsmGeometry(OSM_JSON)
    site = spec.site_cells(geo)
    spec.G = detect_ground(geo, spec, site)
    print("地面 G =", spec.G)
    con = Construction(name, site, y0=spec.G, y1=-30)
    return spec, geo, site, con


def preview(spec, geo, site, tag):
    blocks = parts.build(spec, geo)
    design = {p: norm(s) for p, s in blocks.items()}
    design.update({(x, y, z): norm(s) for (x, y, z, s) in blocks.ordered + blocks.decor})  # 自動扉は開いた状態で描く
    if hasattr(spec, "sign_images") and hasattr(spec, "signs"):   # 看板の地図アートも薄い板として描く
        import map_art as M
        from render import register_panel
        imgs = spec.sign_images()
        for sign in spec.signs(geo):
            tiles = M.split_tiles(imgs[sign[0]], sign[1], sign[2])
            for r, col, cell, _, facing in parts.sign_cells(sign):
                key = f"minecraft:mapart_{sign[0]}_{r}_{col}"
                register_panel(key, tiles[r][col], facing)
                design[cell] = key
    xs, zs = [c[0] for c in site], [c[1] for c in site]
    snap = load_area(min(xs) - 60, min(zs) - 60, max(xs) + 60, max(zs) + 60, y0=-64, y1=-10)
    over = {(x, y, z): AIR for (x, z) in site for y in range(spec.G + 1, -29)}
    over.update(design)
    sc = VoxelScene(snap, over)
    for cam_name, cam in getattr(spec, "CAMERAS", {}).items():
        cam = dict(cam)
        rx, ry, rz = cam.pop("rel_pos")  # y は地面からの高さ
        cam.setdefault("vfov", VIEW["fov"])  # 写真に合わせたカメラは vfov を書く。書かなければゲームの視野角
        render_view(sc, (rx, spec.G + ry, rz), **cam).save(OUT / f"{tag}_{cam_name}.png")
    render_top(sc, px=6).save(OUT / f"{tag}_top.png")
    print(f"{len(design)} ブロック / 敷地 {len(site)} セル → {OUT}")


def place_signs(spec, geo, con):
    """看板を地図アートで置く。サーバーは読んだ地図をキャッシュするので、施工のたびに新しい id を使う。"""
    if not (hasattr(spec, "sign_images") and hasattr(spec, "signs")):
        return
    import map_art as M
    # 建物ごとの施工番号から決めると建物同士で id がぶつかるので、既存の地図ファイルの最大 id の次から使う
    used = [int(p.stem.removeprefix("map_")) for p in (M.WORLD / "data").glob("*.dat")
            if p.stem.removeprefix("map_").isdigit()]
    next_id = max([30000] + [u + 1 for u in used if u >= 30000])
    imgs = spec.sign_images()
    frames = []
    for sign in spec.signs(geo):
        name, cols, rows = sign[:3]
        tiles = M.split_tiles(imgs[name], cols, rows)
        for r, col, (x, y, z), _, facing in parts.sign_cells(sign):
            M.write_map(next_id, tiles[r][col])
            frames.append((x, y, z, facing, next_id))
            next_id += 1
    con.place_frames(frames)
    if frames:
        print(f"看板: 額縁 {len(frames)} 枚（地図 id {frames[0][4]}〜{frames[-1][4]}）")


def demolish(spec, geo, con):
    """解体: 元の建物の土台からつながるブロック（はみ出した屋根・柵など）を、敷地の外まで追って消す。
    ほかの建物（OSM の building）のセルには入らない。"""
    from world_reader import WORLD
    footprint = cells_in(geo.polygon(spec.WAY))
    protect = set()
    fx = [x for x, _ in footprint]
    fz = [z for _, z in footprint]
    for wid, w in geo.ways.items():
        if wid == spec.WAY or "building" not in (w.get("tags") or {}):
            continue
        poly = geo.polygon(wid)
        if all(abs(x - fx[0]) > 80 or abs(z - fz[0]) > 80 for x, z in poly):
            continue
        protect |= cells_in(poly)
    protect -= footprint
    con.add_demolition(con.find_connected(footprint, spec.G, protect), WORLD)


def report(spec, geo):
    """施工の前の自動チェック（すき間・沈んだ看板・見える回路）。警告があれば True。"""
    warns = checks.inspect(checks.design(spec, geo), spec, geo)
    for w in warns:
        print("警告:", w)
    if not warns:
        print("チェック: すき間・沈んだ看板・見える回路は見つかりませんでした")
    return bool(warns)


def main(argv):
    name, cmd = argv[0], (argv[1] if len(argv) > 1 else "preview")
    spec, geo, site, con = load(name)
    if cmd == "preview":
        preview(spec, geo, site, argv[2] if len(argv) > 2 else "preview")
        report(spec, geo)
    elif cmd == "section":   # 断面の AA。引数が無ければ設計の sections(geo) の断面を全部
        D = checks.design(spec, geo)
        cuts = [("", argv[2], int(argv[3]))] if len(argv) > 3 else getattr(spec, "sections", lambda g: [])(geo)
        for label, axis, value in cuts:
            print(f"■ {label}" if label else "", checks.section(D, axis, value, spec.G), "", sep="\n")
    elif cmd == "check":
        report(spec, geo)
    elif cmd in ("build", "reset") and os.environ.get("REMODEL_WORLD"):
        sys.exit("REMODEL_WORLD はプレビュー専用です（施工はサーバーのワールドだけ）")
    elif cmd == "build":
        if report(spec, geo) and "force" not in argv[2:]:
            sys.exit("警告をなくしてから施工します（意図どおりなら、ユーザーに確かめてから build force）")
        demolish(spec, geo, con)
        blocks = parts.build(spec, geo)
        con.build(blocks, clear_from_y=spec.G + 1, note=" ".join(argv[2:]))
        con.place_ordered(blocks.ordered)   # 自動扉のピストンなど（置くと通電で動く）
        con.place_ordered(blocks.decor, label="飾り", verify=True)   # ランタン・トーチ等は最後に取り付けて確かめる
        place_signs(spec, geo, con)
    elif cmd == "reset":
        con.reset()


if __name__ == "__main__":
    main(sys.argv[1:])
