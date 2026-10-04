"""
設計ファイルを施工する入口（どの建物でも共通）。
  python run.py <設計名> preview [タグ]   … ワールドに置かず、写真と同じ視点の絵を out/ に描く
  python run.py <設計名> build ["メモ"]   … 施工（初回は敷地の控え baseline を自動で取る）＋看板の地図アート
  python run.py <設計名> reset           … 更地（baseline）に戻す（看板の額縁も消す）
  python run.py <設計名> section [x|z 値] … 横から見た断面の AA（無ければ設計の sections(geo) の断面）
  python run.py <設計名> check           … 施工の前の自動チェック（build の前にも必ず走る。警告があれば止まる）
  python run.py <設計名> capture [保存先] … 今のワールドの敷地を正解として保存（ゲーム内で手直しした状態。看板の額縁は入らない）
  python run.py <設計名> diff [正解]      … 設計と正解の違いを、ブロックの組み合わせごとに数える
  python run.py <設計名> export [保存先]  … 設計そのものを正解の控えとして書き出す（施工せずに正解を作る）
  python run.py <設計名> faces           … 面ごとの長さ（SHAPE で整えた後）。質問のスライダーの length はこの長さにする
  python run.py <設計名> doortest        … 自動扉の試験（感圧板に防具立てを置いて開閉を確かめる。誰かがログインしている時だけ）
<設計名> は designs/<設計名>.py。
"""

import importlib
import json
import os
import re
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
    probe = set(c for c in site if c not in around)
    top = {}
    base = HERE / "builds" / spec.__name__ / "baseline.json"
    if base.exists():   # 施工したあとは、まわりに置いた物で地面が上がって見えるので、施工前の控えで測る
        b = json.loads(base.read_text(encoding="utf-8"))
        for x, y, z, i in b["blocks"]:
            if (x, z) in probe and norm(b["palette"][i]) != AIR and y > top.get((x, z), -999):
                top[(x, z)] = y
    if not top:
        xs, zs = [c[0] for c in probe], [c[1] for c in probe]
        snap = load_area(min(xs), min(zs), max(xs), max(zs), y0=-64, y1=0)
        for (x, y, z) in snap.blocks:
            if (x, z) in probe and y > top.get((x, z), -999):
                top[(x, z)] = y
    return Counter(top.values()).most_common(1)[0][0]


def check_world_scale(geo):
    """ワールド倍率を毎回表示する。既定の 1.4 でなければ、ユーザーに確かめて REMODEL_SCALE=<倍率> を付けるまで止める
    （建物の縮め方・車線の幅・質問の大きさがすべて倍率で変わるため）。"""
    s = parts.world_scale(geo)
    print(f"ワールド倍率 = {s:g}（建物の幅・奥行き = {s - 0.1 if s > 1 else s:g} 倍、1車線 = {parts.lane_blocks(geo)} マス、"
          f"対面通行の駐車場入口 = {parts.lane_blocks(geo, 2)} マス）")
    if s != parts.DEFAULT_WORLD_SCALE and os.environ.get("REMODEL_SCALE") != f"{s:g}":
        sys.exit(f"ワールド倍率が {s:g} です（既定は {parts.DEFAULT_WORLD_SCALE:g}）。この倍率で作ってよいかユーザーに確かめ、"
                 f"よければ REMODEL_SCALE={s:g} を付けて実行し直してください")


def load(name: str):
    spec = importlib.import_module(name)
    geo = OsmGeometry(OSM_JSON)
    check_world_scale(geo)
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
    cams = spec.cameras(geo) if hasattr(spec, "cameras") else getattr(spec, "CAMERAS", {})   # cameras(geo) なら座標を書かずに置ける
    for cam_name, cam in cams.items():
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


def other_buildings(spec, geo):
    """近くのほかの建物（OSM の building）のセル。解体でも違いの比較でも触らない。"""
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
    return protect - footprint


def demolish(spec, geo, con):
    """解体: 元の建物の土台からつながるブロック（はみ出した屋根・柵など）を、敷地の外まで追って消す。
    ほかの建物（OSM の building）のセルには入らない。"""
    from world_reader import WORLD
    footprint = cells_in(geo.polygon(spec.WAY))
    con.add_demolition(con.find_connected(footprint, spec.G, other_buildings(spec, geo)), WORLD)


def capture(spec, geo, site, path):
    """今のワールドの敷地のブロックと看板の額縁を、正解として保存する（ユーザーがゲーム内で手直しした状態を残す）。
    額縁は、設計の看板のマスごとに「付いているか」を調べる（外された段が分かる）。"""
    from builder import rcon
    frames = {}
    with rcon() as m:
        print("セーブ:", m.command("save-all flush")[:60])
        for sign in (spec.signs(geo) if hasattr(spec, "signs") else []):
            for _, _, (x, y, z), _, _ in parts.sign_cells(sign):
                r = m.command(f"execute if entity @e[type=minecraft:item_frame,x={x + .5},y={y + .5},z={z + .5},distance=..0.7]")
                frames[f"{x},{y},{z}"] = sign[0] if "passed" in r else None
    xs, zs = [c[0] for c in site], [c[1] for c in site]
    snap = load_area(min(xs), min(zs), max(xs), max(zs), y0=spec.G - 2, y1=-25)
    blocks = {f"{x},{y},{z}": s for (x, y, z), s in snap.blocks.items()
              if (x, z) in site and norm(s) != AIR}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": spec.__name__, "way": spec.WAY, "G": spec.G, "y": [spec.G - 2, -25],
                                "note": "blocks: 敷地の空気以外のブロック。frames: 設計の看板のマス → 額縁が付いていれば看板の名前、無ければ null。キーは x,y,z",
                                "blocks": blocks, "frames": frames}, ensure_ascii=False, indent=0), encoding="utf-8")
    missing = [k for k, v in frames.items() if v is None]
    print(f"正解: {len(blocks)} ブロック、額縁 {len(frames) - len(missing)}/{len(frames)} 枚 → {path}")


def export(spec, geo, site, path):
    """設計そのものを正解の控え（capture と同じ形）として書き出す。ゲームに施工せずに正解を作る時に使う。"""
    D = checks.design(spec, geo)
    blocks = {f"{x},{y},{z}": s for (x, y, z), s in D.items()
              if (x, z) in site and s != checks.SIGN and norm(s) != AIR}
    frames = {f"{x},{y},{z}": sign[0] for sign in (spec.signs(geo) if hasattr(spec, "signs") else [])
              for _, _, (x, y, z), _, _ in parts.sign_cells(sign)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": spec.__name__, "way": spec.WAY, "G": spec.G, "y": [spec.G - 2, -25],
                                "note": "設計から書き出した正解（施工していない）。形は capture と同じ",
                                "blocks": blocks, "frames": frames}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"正解（設計から）: {len(blocks)} ブロック、額縁 {len(frames)} 枚 → {path}")


def diff(spec, geo, site, path):
    """設計と正解（capture）の違い。何をどう手直しされたかを、ブロックの組み合わせごとに数える。"""
    ans = json.loads(path.read_text(encoding="utf-8"))
    A = {tuple(map(int, k.split(","))): s for k, s in ans["blocks"].items()}
    D = checks.design(spec, geo)
    y0, y1 = ans["y"]
    skip = other_buildings(spec, geo)

    def key(s):
        if s is None or s == checks.SIGN:      # 額縁のマスはブロックとしては空き（額縁は下で別に比べる）
            return "air"
        n = checks.name(s)
        for prop in ("type", "half", "facing", "hanging"):   # 形と向きは比べる（柵のつながり等は比べない）
            m = re.search(rf"{prop}=(\w+)", s)
            if m and (prop != "facing" or "stairs" in n or "piston" in n) and (prop, m.group(1)) != ("hanging", "false"):
                n += f"[{prop}={m.group(1)}]"
        return n
    pairs, cells = Counter(), {}
    door = {(x, z) for (x, y, z, st) in parts.build(spec, geo).ordered}   # 自動扉の動く所（開け閉めで変わる）
    door |= {(x + dx, z + dz) for (x, z) in door for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
    # 施工が管理している範囲（控えの範囲か、設計が地面より上に何か置く列）だけ比べる。外は元からある物
    bpath = HERE / "builds" / spec.__name__ / "baseline.json"
    bx0, bz0, bx1, bz1 = json.loads(bpath.read_text(encoding="utf-8"))["box"] if bpath.exists() else (0, 0, -1, -1)
    used_cols = {(x, z) for (x, y, z) in D if y > spec.G}
    managed = {(x, z) for (x, z) in site if bx0 <= x <= bx1 and bz0 <= z <= bz1} | used_cols
    for (x, z) in (site & managed) - skip - door:
        for y in range(max(y0, spec.G), y1):
            d, a = key(D.get((x, y, z))), key(A.get((x, y, z)))
            if y == spec.G and (x, y, z) not in D:
                continue                          # 地面で設計に無い所は元の地面
            if d != a:
                pairs[(d, a)] += 1
                cells.setdefault((d, a), []).append((x, y - spec.G, z))
    for k, v in (ans.get("frames") or {}).items():         # 看板: 設計にある額縁が、正解で外されているか
        x, y, z = map(int, k.split(","))
        if v is None and D.get((x, y, z)) == checks.SIGN:
            pairs[("看板の額縁", "air")] += 1
            cells.setdefault(("看板の額縁", "air"), []).append((x, y - spec.G, z))
    print(f"違い: {sum(pairs.values())} マス（設計 → 正解）")
    for (d, a), n in pairs.most_common(40):
        ex = cells[(d, a)][:3]
        print(f"  {n:4d}  {d} → {a}   例（x, 地面からの段, z）{ex}")


def door_test(spec, geo):
    """自動扉の試験: 感圧板に防具立てを置いて開くか、消して閉じるかを確かめる。
    誰もログインしていないとサーバーの時間が止まり、ピストンが動かないので、先に確かめる。"""
    import time
    from builder import rcon
    blocks = parts.build(spec, geo)
    P = {**parts.DEFAULT_PAL, **getattr(spec, "PAL", {})}
    glass = [(x, y, z) for x, y, z, s in blocks.ordered if s == P["door_glass"]]   # 開いた時（引き込んだ）ガラス
    plates = [(x, y, z) for x, y, z, s in blocks.decor if s == P["door_plate"]]
    if not glass or not plates:
        print("自動扉がありません")
        return
    cols = sorted({(x, z) for x, _, z in glass})
    ys = sorted({y for _, y, _ in glass})
    (x0, z0), (x1, z1) = cols[0], cols[-1]
    door = [(x, y, z) for x in range(min(x0, x1), max(x0, x1) + 1) for z in range(min(z0, z1), max(z0, z1) + 1)
            if (x, z) not in cols for y in ys]                    # 閉じた時にガラスが来るマス

    def state(m):
        return ["glass" if "passed" in m.command(f"execute if block {x} {y} {z} {P['door_glass']}") else "air"
                for x, y, z in door]
    with rcon() as m:
        if m.command("list").startswith("There are 0"):
            print("誰もログインしていないので、ピストンが動きません（pause-when-empty）。ログインしてからもう一度")
            return
        print("試験の前（閉じているはず）:", "閉" if all(s == "glass" for s in state(m)) else f"開いている {state(m)}")
        for x, y, z in plates:
            m.command(f"summon armor_stand {x + .5} {y} {z + .5} {{Tags:[\"doortest\"],Invisible:1b}}")
            time.sleep(1.5)
            opened = all(s == "air" for s in state(m))
            m.command("kill @e[type=armor_stand,tag=doortest]")
            time.sleep(1.5)
            closed = all(s == "glass" for s in state(m))
            print(f"感圧板 ({x}, {y}, {z}): 乗ると{'開いた' if opened else '開かない'}、降りると{'閉じた' if closed else '閉じない'}")


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
    elif cmd == "doortest":
        door_test(spec, geo)
    elif cmd == "faces":   # 面ごとの長さ（SHAPE で整えた後）。質問のスライダーの length に使う
        c = parts.Ctx(spec, geo, 7)
        for face, label in (("w", "西"), ("n", "北"), ("e", "東"), ("s", "南")):
            f = parts.Facade(c, face)
            lo, hi = min(f.rows) - f.a0, max(f.rows) - f.a0
            print(f"{label}の面: 面全体 {hi - lo + 1} マス（左の角からの k が {lo}〜{hi}）、"
                  f"そのうち一番長いまっすぐな壁 {f.width} マス（k が 0〜{f.width - 1}）")
    elif cmd in ("capture", "diff", "export"):   # 正解の保存先（既定は builds/<設計名>/answer.json）
        path = Path(argv[2]) if len(argv) > 2 else HERE / "builds" / name / "answer.json"
        {"capture": capture, "diff": diff, "export": export}[cmd](spec, geo, site, path)
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
