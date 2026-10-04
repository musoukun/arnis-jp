"""
部品の早見表（.claude/skills/image2mc-builder/parts.md）を parts.py から作り直す。
parts.py の部品を足したり引数を変えたりしたら、これを実行する: python parts_ref.py
"""

import inspect
from pathlib import Path

import parts

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / ".claude" / "skills" / "image2mc-builder" / "parts.md"
INNER = {"build", "roof", "ring_of", "distance_inward", "connect", "is_decor", "cells_in", "outline", "Ctx", "Blocks",
         "sign_cells"}   # 組み立ての内部（設計からは呼ばない）

HEAD = """# 部品の早見表（parts.py）

`python tools/remodel/parts_ref.py` で parts.py から自動で作る（手で直さない）。**設計を書く時は、parts.py のコードを読まずにこの表を見る。**
どのブロックで作るかは [部位の辞書](recipes.md)、どの部品で置くかはこの表。

## 設計のフォルダの型（designs/_parts_template/）

新しい建物は **`tools/remodel/designs/_parts_template/` をフォルダごと `designs/<建物名>/` にコピー**し、★ を全部埋める（既定は空。何を選ぶかは [辞書](recipes.md)の「手札」）。
建物を部位ごとのファイル（パーツ）に分け、パーツは Sonnet の Agent が1つずつ並列に書く。組み立ては `__init__.py`（`tools/remodel/assemble.py`）が自動でやる。

| ファイル | だれが書く | 中身 |
|---|---|---|
| `base.py` | 親 | 約束。`WAY` / `EXCLUDE` / `PHOTO`、`STACK` / `ROOF` / `WINDOW_FACES` / `PILLAR_EVERY` / `PLINTH` / `PAL` / `BAND`（壁の段・屋根・窓の面・柱の間隔・土台・素材・帯のハーフ）、`SHAPE`（建物の形を整える量。`parts.grow_footprint`）、`ENTRANCE`（入口の型と位置。辞書「入口の型の選び方」）、`footprint(geo)` / `site_cells(geo)`、`cameras(c)`（`parts.camera`）、`sections(c)`（断面） |
| `plan.md` | 親 | 受け持ちの表。面の長さ・質問の答え・部位表と、どの Agent がどのファイルを書くか（1行 = 1 Agent = 1ファイル） |
| `p_<名前>.py` | Agent | パーツ1つ。下の形（書き方の例は `_example_part.py`。名前が _ で始まるので組み立てには入らない） |
| `__init__.py` | （型のまま） | 組み立て役。書き換えない |

パーツの形（使う物だけ書く）:

| 名前 | 中身 |
|---|---|
| `ORDER = 20` | 組み立ての順。屋上 10 → 帯 15 → 面ごと 20 → 外まわり 30 → 看板 40 |
| `part(c)` | ブロックを置く |
| `signs(geo, c)` | 看板の一覧 `[(名前, 列, 行, 左上の額縁 (x, y, z), 向き)]`。名前はほかのパーツと重ねない |
| `BACKING = {名前: ブロック}` | 看板の裏のブロック（None は壁に直接） |
| `images()` | 看板の絵 `{名前: 絵}`（下の「看板の絵」） |

入口と室内は、組み立て役が `base.py` の `ENTRANCE` から**最後に**置く（パーツに書かない）:
- `dict(kind="衝立つき", face, door_k, poster, auto, left_gap, right_gap, bed_end)` … 衝立・通り道・植え込み・左右の通路・扉・帯の延長（`front_entrance`）。
  `poster=True` なら衝立にポスター（位置は組み立て役。パーツは絵だけを `images()` の `"poster"`（2×3）で描く）
- `dict(kind="扉だけ", face, door_k, steps, auto)` … 壁の線の扉と段（`entrance`）。`steps` は `"landing"` / `"slab"` / `"stairs"`
- どちらも `auto=True` ならガラスの自動扉（`auto_door`、`PLINTH = 1` が要る）。`ENTRANCE = None` なら入口を置かない
パーツ1つだけを試す: `REMODEL_ONLY=<p_ を除いた名前> python run.py <建物名> preview <名前>`（カンマ区切りで複数）。

## part(c) の中で使えるもの（c = parts.Ctx）

| 名前 | 中身 |
|---|---|
| `c.G` / `c.F` / `c.top` | 地面の段 / 床の段（土台があれば地面+1）/ 帯・天井の段。**高さはこの3つから書く**（接する部位は相手の基準で） |
| `c.bld` / `c.roof` / `c.site` | 建物のセル (x, z) の集合 / 屋根のセル / 敷地のセル |
| `c.wall` | 外周の壁のセル → 外に面した向きのリスト（`"n"`/`"s"`/`"w"`/`"e"`） |
| `c.pal` | 素材（`parts.DEFAULT_PAL` に設計の `PAL` を重ねた物） |
| `c.put(x, y, z, ブロック)` | 1マス置く（部品で置けない物だけ。飾りは自動で最後に取り付ける） |
| `parts.STEP` | 向き → 外への1マス `{"n": (0,-1), "s": (0,1), "w": (-1,0), "e": (1,0)}` |

## 看板の絵（tools/remodel/sign_art.py）

店の顔（ロゴ・店名・壁の看板・立て看板・ポスター）は**必ず地図アート**にする。
**写真から看板の中身（文字・色・形・配置）を読み取り、次の型で描く**（写真を切り抜かない。斜め・小さい・反射でぼやけるため）。
パーツの `images()` で看板ごとの絵を返す（1マス = 128px）:

| 型 | 使う所 |
|---|---|
| `sign_art.text(["SHOP"], 5, 2)` | 壁に直接貼る白い文字（背景は透明。`SIGN_BACKING` は None） |
| `sign_art.framed(3, 3, frame="red", fill="white", inner="SHOP")` | 枠付きのロゴ（`inner` は文字か画像） |
| `sign_art.panel(5, 3, "black", ["24H", "OPEN", "SINCE 1970"])` | 黒地などに数行の文字の看板 |
| `sign_art.arrow(3, 2, "left", label="入口", accent=(200, 25, 30))` | 矢印の案内板 |
| `sign_art.shapes(2, 3, "skyblue", [("rect", …), ("circle", …), ("text", …), ("poly", …)])` | 写真から読んだ形を並べて描く（ポスター・紋章・顔のロゴなど）。位置は看板の幅・高さの割合 |
| `sign_art.from_photo(PHOTO, (左, 上, 右, 下), 3, 3)` | （最後の手段）描けないほど込み入った時だけ、写真を切り抜く |

描いた例（ロゴを読んで描く）: 「白地に赤い枠、下に赤い帯、黒い線の顔」と読んだら
`sign_art.shapes(3, 3, "white", [("rect", (0, .72, 1, 1), "red"), ("circle", (.5, .35, .2), "black", 12)])` に
`framed` の赤い枠を重ねる、のように、写真の形を丸・四角・線に置き換える。

看板の位置は `signs(geo, c)` の中で `parts.Facade(c, 面).at(k, out=1)`（壁に直接）か `out=2`（1マス飛び出す）で求め、
高さは `c.top`（帯の段）や `c.G` から書く。

## 部品
"""


def main():
    rows = []
    for name, obj in vars(parts).items():
        if name.startswith("_") or name in INNER or not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue
        if getattr(obj, "__module__", "") != "parts":
            continue
        line = inspect.getsourcelines(obj)[1]
        sig = str(inspect.signature(obj.__init__ if inspect.isclass(obj) else obj)).replace("(self, ", "(")
        doc = inspect.getdoc(obj) or ""
        rows.append((line, name, sig, doc))
    out = [HEAD]
    for _, name, sig, doc in sorted(rows):
        out += [f"### `{name}{sig}`", "", doc, ""]
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"{len(rows)} 個の部品 → {OUT}")


if __name__ == "__main__":
    main()
