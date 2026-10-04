"""
施工の前の確かめ（building-remodel スキルの「一発で建てる」ための自動チェック）。

  design(spec, geo)           … 設計の全ブロック（本体・仕掛け・飾り・看板の額縁）を1つの辞書に
  section(D, axis, value, G)  … 横から見た断面の AA（凡例つき）。お手本と見比べてから施工する
  inspect(D, spec, geo)       … すき間・沈み・見える回路を探して、警告の一覧を返す（空なら合格）

使い方: python run.py <建物> section [x|z 値]   /   python run.py <建物> check
"""

import parts

SIGN = "#sign"     # 看板の額縁が付くセル（AA では「看」）


def name(s):
    return "air" if s is None else s.split("[")[0].split("{")[0].replace("minecraft:", "")


def design(spec, geo):
    blocks = parts.build(spec, geo)
    D = dict(blocks)
    D.update({(x, y, z): s for x, y, z, s in blocks.ordered + blocks.decor})
    for sign in (spec.signs(geo) if hasattr(spec, "signs") else []):
        for _, _, cell, _, _ in parts.sign_cells(sign):
            D[cell] = SIGN
    return D


# ---------------- 断面の AA ----------------

_FIXED = {"air": " ", SIGN: "看"}


def section(D, axis, value, G, pad=1):
    """axis="z" なら z=value で切って、横軸 x（西→東）。axis="x" なら x=value、横軸 z（北→南）。
    設計に無いセル（地面より下は元の地面、上は空き）は「.」。"""
    cut = [(p, s) for p, s in D.items() if (p[2] if axis == "z" else p[0]) == value]
    if not cut:
        return f"{axis}={value} に設計のブロックがありません"
    hs = [p[0] if axis == "z" else p[2] for p, _ in cut]
    ys = [p[1] for p, _ in cut]
    h0, h1, y0, y1 = min(hs) - pad, max(hs) + pad, max(G - 1, min(ys)), max(ys)
    sym, legend = dict(_FIXED), []
    letters = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    rows = []
    for y in range(y1, y0 - 1, -1):
        line = []
        for h in range(h0, h1 + 1):
            p = (h, y, value) if axis == "z" else (value, y, h)
            if p not in D:
                line.append(".")
                continue
            n = name(D[p]) if D[p] != SIGN else SIGN
            if "type=bottom" in D[p]:
                n += "(下ハーフ)"
            elif "type=top" in D[p]:
                n += "(上ハーフ)"
            if n not in sym:
                sym[n] = next(letters)
                legend.append(f"  {sym[n]} = {n}")
            line.append(sym[n])
        rows.append(f"{y - G:+4d} |{''.join(line)}|")
    head = "西 → 東" if axis == "z" else "北 → 南"
    return "\n".join([f"断面 {axis}={value}（{head}。縦は地面からの段、+0 が地面）"] + rows + ["凡例:", "  看 = 看板の額縁",
                                                                       "  . = 設計に無い（元の地面か空き）"] + legend)


# ---------------- 自動チェック ----------------

_SEE_THROUGH = ("air", "glass", "pane", "fence", "iron_bars", "slab", "stairs", "chain", "lantern", "torch",
                "pressure_plate", "wall", "carpet", "trapdoor", "door", SIGN)
_CIRCUIT = ("redstone_wire", "redstone_torch", "repeater", "comparator", "observer")
STEP6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def _see_through(D, p, G):
    if p not in D:
        return p[1] > G                       # 設計に無いセル: 地面より上は空き、下は元の地面
    return any(w in name(D[p]) or D[p] == SIGN for w in _SEE_THROUGH)


def _filled(D, p):
    """ブロックが入っている（空き・飾り・看板の額縁ではない）。ハーフや塀も「入っている」に数える。"""
    return p in D and D[p] != SIGN and name(D[p]) != "air" and not parts.is_decor(D[p])


def inspect(D, spec, geo):
    """警告の一覧（文字列）を返す。施工の前に全部なくす（直すか、意図どおりならユーザーに確かめる）。"""
    G = spec.G
    bld, _ = spec.footprint(geo) if hasattr(spec, "footprint") else (parts.cells_in(geo.polygon(spec.WAY)), None)
    warns = []

    # 1. 建物の外の細長いすき間: 上下をブロックに挟まれた高さ1の空きが横に2マス以上続く（帯の下・衝立の上など）
    gaps = []
    for (x, y, z), s in D.items():
        if (x, z) in bld or y <= G + 1 or not _filled(D, (x, y, z)):
            continue
        below, below2 = (x, y - 1, z), (x, y - 2, z)
        if name(D.get(below)) == "air" and _filled(D, below2):
            gaps.append((x, y - 1, z))
    g = set(gaps)                             # 1マスだけの空き（看板の2本の足のあいだ等）は除き、横に続く細長いすき間だけ
    gaps = sorted(p for p in g if any((p[0] + a, p[1], p[2] + c) in g for a, _, c in STEP6 if (a, c) != (0, 0)))
    if gaps:
        warns.append(f"すき間: 建物の外に、上下をブロックに挟まれた高さ1マスの細長い空きが {len(gaps)} か所"
                     f"（例 {gaps[:3]}）。帯の下や衝立の上なら、下の部位を帯の真下まで届かせる")

    # 2. 沈んだ看板: 一番下の段が地面のすぐ上（足元）にある
    for sign in (spec.signs(geo) if hasattr(spec, "signs") else []):
        nm, _, rows, (_, fy, _) = sign[:4]
        bottom = fy - (rows - 1)
        if bottom <= G + 1:
            warns.append(f"沈んだ看板: 「{nm}」の一番下が地面+{bottom - G}（足元）。植え込みや台の上に載せる")

    # 3. 見える回路: レッドストーンの粉・トーチの隣（上下左右前後）が、空き・ガラス・柵など透ける物
    shown = [p for p, s in D.items() if any(w in name(s) for w in _CIRCUIT)
             and any(_see_through(D, (p[0] + a, p[1] + b, p[2] + c), G) for a, b, c in STEP6)]
    if shown:
        warns.append(f"見える回路: レッドストーンが {len(shown)} か所で外から見える（例 {shown[:3]}）。"
                     "石レンガで包むか、床下に入れる")
    return warns
