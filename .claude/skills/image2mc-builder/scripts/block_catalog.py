"""
ブロックの色の対応表（全ブロック）と、写真の色 → ブロックの見比べ。

  python block_catalog.py build                        … 対応表を作る（block_catalog.json と out/block_catalog.html）
  python block_catalog.py samples <ブロック名>...     … 一覧表と同じ見本の画像（data URI の JSON）。質問のフォーム用
  python block_catalog.py match <写真> x0 y0 x1 y1 [件数] [名前の絞り込み]
                                                       … 写真の範囲の色に近いブロックを、実物のテクスチャと並べた絵にする

対応表は クライアント jar の blockstates → models → textures をたどって作る（名前の推測ではない）。
ブロックごとに:
  side / top   側面・上面のテクスチャ名
  avg          平均色
  dominant     一番多く使われている色の範囲（RGB を 8 段階ずつに区切った箱のうち最多の箱）の平均色
  share        その範囲が占める割合（1 に近いほど単色。低いほど模様・まだら）
  full         普通の立方体か（壁・床に使えるか）
  color        表と見比べに使う色。ふつうは dominant。白っぽい一部のブロック（AVG_BLOCKS）は avg
写真と比べるときは color を使う（平均色は模様の色が混ざって、見た目の色とずれる）。
ただし、白い所が一番多いだけで見た目は白でないブロック（ケーキ・シラカバの丸太・フロッグライト等）は、
一番多い色だと真っ白になって見た目とずれるので、平均色を使う（ユーザー指定、2026-10-04）。
"""

import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from block_colors import JAR, _TINT, rgb_to_lab

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "block_catalog.json"
OUT = HERE / "out"
FONT = "C:/Windows/Fonts/BIZ-UDGothicR.ttc"
_FOLIAGE = (0.38, 0.6, 0.2)  # 葉はバイオームの緑が掛かる（桜・ツツジ・ペールオークは掛からない）
_NO_TINT_LEAVES = ("cherry_leaves", "azalea_leaves", "flowering_azalea_leaves", "pale_oak_leaves")


def _json(z, path):
    return json.loads(z.read(path))


def _model_textures(z, model):
    """モデル名 → (textures dict, 立方体か)。parent をたどって textures を合わせ、#参照を解く。"""
    tex, full, name = {}, False, model
    while name:
        name = name.replace("minecraft:", "")
        if name in ("block/cube", "block/cube_all", "block/cube_column", "block/cube_bottom_top",
                    "block/cube_column_horizontal", "block/orientable", "block/leaves"):
            full = True
        try:
            m = _json(z, f"assets/minecraft/models/{name}.json")
        except KeyError:
            break
        for k, v in (m.get("textures") or {}).items():
            tex.setdefault(k, v)
        if any(e.get("from") == [0, 0, 0] and e.get("to") == [16, 16, 16] for e in m.get("elements") or []):
            full = True
        name = m.get("parent")
    for _ in range(5):
        for k, v in tex.items():
            if isinstance(v, str) and v.startswith("#"):
                tex[k] = tex.get(v[1:], v)
    return tex, full


def _first_model(state):
    if "variants" in state:
        v = next(iter(state["variants"].values()))
    else:
        v = state["multipart"][0]["apply"]
    return (v[0] if isinstance(v, list) else v)["model"]


def _pick(tex, keys):
    for k in keys:
        v = tex.get(k)
        if isinstance(v, str) and not v.startswith("#"):
            return v.replace("minecraft:", "").replace("block/", "")
    return None


def _pixels(z, tex):
    """テクスチャ → 不透明な画素 (N,3) 0..255。葉・草は緑を掛ける。"""
    img = Image.open(io.BytesIO(z.read(f"assets/minecraft/textures/block/{tex}.png"))).convert("RGBA")
    a = np.asarray(img, dtype=np.float32)
    a = a[:a.shape[1]]  # アニメーションは1コマ目
    px = a[a[..., 3] > 128][:, :3]
    tint = _TINT.get(tex) or (_FOLIAGE if tex.endswith("_leaves") and tex not in _NO_TINT_LEAVES else None)
    if tint:
        px = px * np.array(tint, dtype=np.float32)
    return px


# 一番多い色ではなく平均色を使うブロック（一番多い色が白で、見た目とずれるもの。ユーザー指定）
AVG_BLOCKS = {"cake", "white_stained_glass", "white_stained_glass_pane", "end_rod", "snow", "snow_block",
              "powder_snow", "white_glazed_terracotta", "verdant_froglight", "pearlescent_froglight",
              "pale_oak_trapdoor", "redstone_wire", "birch_log", "birch_wood"}


def use_avg(block):
    """平均色を使うか。鉱石（_ore）とテラコッタ（terracotta）は、模様の色を混ぜた平均にする（ユーザー指定）。"""
    return block in AVG_BLOCKS or block.endswith("candle_cake") or "_ore" in block or "terracotta" in block


def dominant(px):
    """画素 → (一番多い色の範囲の平均色, その割合)。RGB を 8 段階ずつ（32 刻み）の箱に分けて数える。"""
    bins = (px // 32).astype(int)
    key = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    top = vals[np.argmax(counts)]
    sel = px[key == top]
    return [int(round(v)) for v in sel.mean(axis=0)], round(len(sel) / len(px), 3)


def build():
    z = zipfile.ZipFile(JAR)
    cat = {}
    for n in sorted(z.namelist()):
        if not (n.startswith("assets/minecraft/blockstates/") and n.endswith(".json")):
            continue
        block = n.rsplit("/", 1)[1][:-5]
        try:
            tex, full = _model_textures(z, _first_model(_json(z, n)))
        except (KeyError, StopIteration, IndexError):
            continue
        side = _pick(tex, ("side", "all", "texture", "front", "end", "cross", "pane", "wool", "particle"))
        top = _pick(tex, ("top", "end", "all", "texture", "side", "particle"))
        if not side:
            continue
        try:
            px = _pixels(z, side)
        except KeyError:
            continue
        if len(px) == 0:
            continue
        dom, share = dominant(px)
        cat[block] = {"side": side, "top": top, "full": full,
                      "avg": [int(round(v)) for v in px.mean(axis=0)], "dominant": dom, "share": share}
        cat[block]["color"] = cat[block]["avg"] if use_avg(block) else dom
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(cat)} ブロック → {CATALOG}")
    _html(z, cat)


def _hex(c):
    return "#%02x%02x%02x" % tuple(c)


def _html(z, cat):
    """全ブロックの一覧（テクスチャ・一番多い色・割合）。色相と明るさで並べ、名前で絞り込める。"""
    def key(item):
        r, g, b = [v / 255 for v in item[1]["color"]]
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 0.08:
            return (0, -mx)  # 無彩色は先頭に明るい順
        h = (((g - b) / (mx - mn)) % 6 if mx == r else (b - r) / (mx - mn) + 2 if mx == g else (r - g) / (mx - mn) + 4)
        return (1 + int(h * 2), -mx)
    tiles = []
    for block, e in sorted(cat.items(), key=key):
        img = Image.open(io.BytesIO(z.read(f"assets/minecraft/textures/block/{e['side']}.png"))).convert("RGBA")
        img = img.crop((0, 0, img.width, img.width)).resize((48, 48), Image.NEAREST)
        buf = io.BytesIO(); img.save(buf, "PNG")
        uri = base64.b64encode(buf.getvalue()).decode()
        tiles.append(
            f'<div class="t{"" if e["full"] else " part"}" data-n="{block}"><img src="data:image/png;base64,{uri}">'
            f'<span class="sw" style="background:{_hex(e["color"])}"></span>'
            f'<b>{block}</b><small>{_hex(e["color"])} '
            f'{"平均" if use_avg(block) else str(round(e["share"] * 100)) + "%"}</small></div>')
    html = f"""<!doctype html><meta charset="utf-8"><title>ブロックの色の対応表</title>
<style>body{{font:12px sans-serif;margin:16px;background:#f4f4f4}}#q{{width:280px;padding:6px}}
.g{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}.t{{width:120px;background:#fff;padding:4px;border-radius:4px}}
.t img{{width:48px;height:48px;image-rendering:pixelated;vertical-align:middle}}
.sw{{display:inline-block;width:48px;height:48px;vertical-align:middle;margin-left:4px;border-radius:3px}}
.t b{{display:block;font-size:11px;word-break:break-all}}.part{{opacity:.55}}</style>
<p>左: テクスチャ / 右: 一番多く使われている色（％はその色の範囲の割合。高いほど単色）。「平均」と書いたものは平均色。薄いのは立方体でないブロック。</p>
<input id="q" placeholder="名前で絞り込み（例: concrete, bricks）">
<label><input type="checkbox" id="f"> 立方体だけ</label><div class="g">{''.join(tiles)}</div>
<script>const q=document.getElementById('q'),f=document.getElementById('f');
function u(){{for(const t of document.querySelectorAll('.t'))t.style.display=(t.dataset.n.includes(q.value)&&(!f.checked||!t.classList.contains('part')))?'':'none'}}
q.oninput=u;f.onchange=u;</script>"""
    OUT.mkdir(exist_ok=True)
    (OUT / "block_catalog.html").write_text(html, encoding="utf-8")
    print(f"一覧 → {OUT / 'block_catalog.html'}")


def sample_uri(block, side=48):
    """一覧表と同じ見本の画像（側面のテクスチャ、data URI）。質問のフォームにブロックの見本を出すのに使う。
    ハーフ（_slab）は下半分だけにして、薄さが分かるようにする。"""
    z = zipfile.ZipFile(JAR)
    e = load()[block]
    img = Image.open(io.BytesIO(z.read(f"assets/minecraft/textures/block/{e['side']}.png"))).convert("RGBA")
    img = img.crop((0, 0, img.width, img.width)).resize((side, side), Image.NEAREST)
    if block.endswith("_slab"):
        img = img.crop((0, side // 2, side, side))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def load():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


# 建物に使わないブロック（テスト用・管理用・虫食い・鉱石・作業台類など）
_SKIP = ("test_", "infested_", "command_block", "structure_", "jigsaw", "barrier", "crafter", "spawner",
         "trial_", "vault", "_ore", "budding_", "reinforced_", "furnace", "smoker", "dispenser", "dropper",
         "observer", "piston", "table", "loom", "beehive", "bee_nest", "target", "tnt", "jukebox", "note_block",
         "sculk", "respawn", "lodestone", "chiseled_bookshelf", "bookshelf", "pumpkin", "melon", "hay_block",
         "mushroom", "coral", "slime", "honey", "sponge", "frosted_ice", "suspicious_", "creaking", "bedrock")


def usable(block):
    return not any(w in block for w in _SKIP)


def nearest(rgb, n=8, full_only=True, like=None):
    """色 → 近いブロック [(名前, 距離)]。各ブロックの color（ふつうは一番多い色）の Lab 距離で比べる。建物に使わないものは除く。"""
    cat = load()
    names = [b for b, e in cat.items() if (e["full"] or not full_only) and usable(b) and (not like or like in b)]
    cols = np.array([cat[b]["color"] for b in names], dtype=np.float64)
    d = np.linalg.norm(rgb_to_lab(cols) - rgb_to_lab(np.asarray(rgb, dtype=np.float64)), axis=-1)
    order = np.argsort(d)[:n]
    return [(names[i], round(float(d[i]), 1)) for i in order]


def match(photo, x0, y0, x1, y1, n=8, like=None):
    """写真の範囲 → その範囲で一番多い色 と、近いブロックのテクスチャを並べた絵（out/match_*.png）。
    like を渡すと名前にそれを含むブロックだけで比べる（例: "bricks" で模様をレンガに絞って色を選ぶ）。"""
    z = zipfile.ZipFile(JAR)
    crop = Image.open(photo).convert("RGB").crop((x0, y0, x1, y1))
    dom, share = dominant(np.asarray(crop, dtype=np.float32).reshape(-1, 3))
    hits = nearest(dom, n, like=like)
    cat = load()
    S, W = 96, 190
    sheet = Image.new("RGB", (S * 2 + 20 + W * n, S + 60), "white")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(FONT, 13)
    c = crop.copy(); c.thumbnail((S, S)); sheet.paste(c, (0, 0))
    d.rectangle((S + 4, 0, S * 2 + 4, S), fill=tuple(dom))
    d.text((0, S + 6), f"写真 {_hex(dom)} ({round(share * 100)}%)", fill="black", font=font)
    for i, (b, dist) in enumerate(hits):
        x = S * 2 + 20 + i * W
        img = Image.open(io.BytesIO(z.read(f"assets/minecraft/textures/block/{cat[b]['side']}.png"))).convert("RGB")
        sheet.paste(img.crop((0, 0, img.width, img.width)).resize((S, S), Image.NEAREST), (x, 0))
        d.text((x, S + 6), b, fill="black", font=font)
        d.text((x, S + 24), f"差 {dist}", fill="gray", font=font)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"match_{Path(photo).stem}_{x0}_{y0}{'_' + like if like else ''}.png"
    sheet.save(path)
    print(f"写真の色 {_hex(dom)}（範囲の {round(share * 100)}%）")
    for b, dist in hits:
        print(f"  {b:32s} 差 {dist}")
    print("→", path)
    return hits


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "build":
        build()
    elif a and a[0] == "samples":
        print(json.dumps({b: sample_uri(b, 16) for b in a[1:]}))
    elif a and a[0] == "match":
        match(a[1], *map(int, a[2:6]), n=int(a[6]) if len(a) > 6 else 8, like=a[7] if len(a) > 7 else None)
    else:
        print(__doc__)
