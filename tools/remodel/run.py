"""
設計ファイルを施工する入口（どの建物でも共通）。
  python run.py <設計名> preview [タグ]   … ワールドに置かず、写真と同じ視点の絵を out/ に描く
  python run.py <設計名> build ["メモ"]   … 施工（初回は敷地の控え baseline を自動で取る）＋看板の地図アート
  python run.py <設計名> reset           … 更地（baseline）に戻す（看板の額縁も消す）
<設計名> は designs/<設計名>.py。
"""

import importlib
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "designs"))

import parts
from builder import AIR, Construction, norm
from parcel import ROOT, OsmGeometry, cells_in
from render import VoxelScene, render_top, render_view
from world_reader import load_area

OUT = HERE / "out"  # プレビュー画像（git 管理外）
OUT.mkdir(exist_ok=True)
OSM_JSON = ROOT / "doc" / "kitahanada" / "osm_data.json"  # arnis が保存した OSM（範囲が違えば osm_cache の方）


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
    design = {p: norm(s) for p, s in parts.build(spec, geo).items()}
    xs, zs = [c[0] for c in site], [c[1] for c in site]
    snap = load_area(min(xs) - 60, min(zs) - 60, max(xs) + 60, max(zs) + 60, y0=-64, y1=-10)
    over = {(x, y, z): AIR for (x, z) in site for y in range(spec.G + 1, -29)}
    over.update(design)
    sc = VoxelScene(snap, over)
    for cam_name, cam in getattr(spec, "CAMERAS", {}).items():
        cam = dict(cam)
        rx, ry, rz = cam.pop("rel_pos")  # y は地面からの高さ
        render_view(sc, (rx, spec.G + ry, rz), **cam).save(OUT / f"{tag}_{cam_name}.png")
    render_top(sc, px=6).save(OUT / f"{tag}_top.png")
    print(f"{len(design)} ブロック / 敷地 {len(site)} セル → {OUT}")


def place_signs(spec, geo, con):
    """看板を地図アートで置く。サーバーは読んだ地図をキャッシュするので、施工のたびに新しい id を使う。"""
    if not (hasattr(spec, "sign_images") and hasattr(spec, "signs")):
        return
    import map_art as M
    no = len(list(con.dir.glob("[0-9][0-9][0-9].json")))
    next_id = 30000 + no * 100
    imgs = spec.sign_images()
    frames = []
    for name, cols, rows, (fx, fy, fz) in spec.signs(geo):
        for r, row in enumerate(M.split_tiles(imgs[name], cols, rows)):
            for c, tile in enumerate(row):
                M.write_map(next_id, tile)
                frames.append((fx, fy - r, fz + c, "west", next_id))
                next_id += 1
    con.place_frames(frames)
    if frames:
        print(f"看板: 額縁 {len(frames)} 枚（地図 id {frames[0][4]}〜{frames[-1][4]}）")


def main(argv):
    name, cmd = argv[0], (argv[1] if len(argv) > 1 else "preview")
    spec, geo, site, con = load(name)
    if cmd == "preview":
        preview(spec, geo, site, argv[2] if len(argv) > 2 else "preview")
    elif cmd == "build":
        con.build(parts.build(spec, geo), clear_from_y=spec.G + 1, note=" ".join(argv[2:]))
        place_signs(spec, geo, con)
    elif cmd == "reset":
        con.reset()


if __name__ == "__main__":
    main(sys.argv[1:])
