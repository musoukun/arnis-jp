"""
看板の絵の型（地図アート用）。パーツの images() から呼んで、看板ごとの絵（PIL の画像）を作る。
1マス = 128px。cols × rows マスの絵を返す（map_art.split_tiles が1マスずつに切る）。

  text(["SHOP"], 5, 2)                                  … 文字だけ（背景は透明＝壁に直接、bg を渡すと塗る）
  framed(3, 3, frame="red", fill="white", inner=...)   … 枠付きのロゴ・看板（inner は文字か画像）
  arrow(3, 2, "left", label="入口")            … 矢印の案内板
  shapes(2, 3, "skyblue", [("circle", (.5, .6, .25), "orange")]) … 写真から読んだ形（丸・四角・文字・多角形）を並べて描く
  from_photo(写真, (x0, y0, x1, y1), 3, 3)              … （最後の手段）写真の看板を切り抜く。ふつうは読んで描く
  panel(5, 3, "black", ["24H", "OPEN", "SINCE 1970"]) … 黒地などに数行の文字

色は "white" などの名前か (R, G, B[, A])。
"""

from PIL import Image, ImageDraw, ImageFont

import map_art as M

S = M.SIZE


def _font(px):
    return ImageFont.truetype(M.FONT_BOLD, max(8, int(px)))


def _fit_text(d, box, text, color, max_px):
    """box（x0, y0, x1, y1）の中に、はみ出さない大きさで文字を真ん中に書く。"""
    x0, y0, x1, y1 = box
    px = max_px
    while px > 8:
        f = _font(px)
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        if r - l <= (x1 - x0) * 0.94 and b - t <= (y1 - y0) * 0.9:
            break
        px *= 0.92
    d.text(((x0 + x1 - (r - l)) / 2 - l, (y0 + y1 - (b - t)) / 2 - t), text, fill=color, font=f)


def panel(cols, rows, bg, lines, fg="white"):
    """bg で塗った板に、数行の文字を上から等分に書く。"""
    img = Image.new("RGBA", (cols * S, rows * S), bg)
    d = ImageDraw.Draw(img)
    h = rows * S / max(len(lines), 1)
    for i, line in enumerate(lines):
        _fit_text(d, (0, i * h, cols * S, (i + 1) * h), line, fg, h * 0.8)
    return img


def text(lines, cols, rows, fg="white", bg=None):
    """文字だけの看板。bg が None なら背景は透明（壁に直接貼る白い文字など。SIGN_BACKING は None にする）。"""
    return panel(cols, rows, bg or (0, 0, 0, 0), lines if isinstance(lines, list) else [lines], fg)


def framed(cols, rows, frame="red", fill="white", inner=None, fg="black", width=0.12):
    """枠付きの看板・ロゴ。inner は文字（str）か画像（PIL）。width は枠の太さ（短い辺に対する割合）。"""
    W, H = cols * S, rows * S
    img = Image.new("RGBA", (W, H), frame)
    d = ImageDraw.Draw(img)
    w = int(min(W, H) * width)
    d.rectangle((w, w, W - w - 1, H - w - 1), fill=fill)
    if isinstance(inner, str):
        _fit_text(d, (w, w, W - w, H - w), inner, fg, (H - 2 * w) * 0.6)
    elif inner is not None:
        pic = inner.copy()
        k = min((W - 2 * w) / pic.width, (H - 2 * w) / pic.height)   # 枠の中いっぱいに（小さい絵は拡大する）
        pic = pic.resize((max(1, int(pic.width * k)), max(1, int(pic.height * k))), Image.LANCZOS)
        img.paste(pic, ((W - pic.width) // 2, (H - pic.height) // 2), pic if pic.mode == "RGBA" else None)
    return img


def arrow(cols, rows, direction="left", fg="white", bg="black", label=None, label_color="white", accent=None):
    """矢印の案内板（入口・駐車場など）。label を上の段に、矢印を下の段に描く。accent は矢印の地の色。"""
    W, H = cols * S, rows * S
    img = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(img)
    top = H * 0.38 if label else 0
    if label:
        _fit_text(d, (0, 0, W, top), label, label_color, top * 0.7)
    if accent:
        d.rectangle((W * 0.05, top + H * 0.05, W * 0.95, H * 0.95), fill=accent)
    cy, x0, x1 = (top + H) / 2, W * 0.15, W * 0.85
    head, shaft = (H - top) * 0.35, (H - top) * 0.12
    if direction == "right":
        x0, x1 = x1, x0
    sgn = 1 if direction != "right" else -1
    d.rectangle((min(x0 + sgn * head, x1), cy - shaft, max(x0 + sgn * head, x1), cy + shaft), fill=fg)
    d.polygon([(x0, cy), (x0 + sgn * head * 1.3, cy - head), (x0 + sgn * head * 1.3, cy + head)], fill=fg)
    return img


def shapes(cols, rows, bg, items):
    """写真から読んだ看板・ポスター・紋章を、形を並べて描く。位置と大きさは看板の幅・高さに対する割合（0〜1）で書く。
    items の1つずつ:
      ("rect", (x0, y0, x1, y1), 色)              … 四角（帯・枠の中の色の区画）
      ("circle", (cx, cy, r), 色[, 線の太さ])       … 丸（食べ物・紋章。線の太さを書くと輪だけ）
      ("text", (x0, y0, x1, y1), "文字", 色)        … 文字（枠の中にはみ出さない大きさで）
      ("poly", [(x, y), ...], 色)                  … 多角形（矢印・旗・三角）
    例: shapes(2, 3, (120, 190, 235), [("rect", (0, 0, 1, .15), "white"), ("circle", (.45, .55, .25), (215, 140, 50))])"""
    W, H = cols * S, rows * S
    img = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(img)
    for it in items:
        kind = it[0]
        if kind == "rect":
            x0, y0, x1, y1 = it[1]
            d.rectangle((x0 * W, y0 * H, x1 * W, y1 * H), fill=it[2])
        elif kind == "circle":
            cx, cy, r = it[1]
            box = (cx * W - r * min(W, H), cy * H - r * min(W, H), cx * W + r * min(W, H), cy * H + r * min(W, H))
            if len(it) > 3:
                d.ellipse(box, outline=it[2], width=int(it[3]))
            else:
                d.ellipse(box, fill=it[2])
        elif kind == "text":
            x0, y0, x1, y1 = it[1]
            _fit_text(d, (x0 * W, y0 * H, x1 * W, y1 * H), it[2], it[3], (y1 - y0) * H * 0.8)
        elif kind == "poly":
            d.polygon([(x * W, y * H) for x, y in it[1]], fill=it[2])
    return img


def from_photo(photo, box, cols, rows):
    """（最後の手段）写真（パス）の box（左, 上, 右, 下 の画素）を切り抜いて、cols × rows マスの絵にする。
    写真の看板は斜め・小さい・反射があり、地図アートにするとぼやける。ふつうは中身（文字・色・形）を読んで
    text / framed / panel / arrow / shapes で描く。切り抜くのは、描けないほど込み入ったロゴの時だけ。"""
    img = Image.open(photo).convert("RGBA").crop(box)
    return img.resize((cols * S, rows * S), Image.LANCZOS)
