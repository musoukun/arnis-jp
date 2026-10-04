# 受け持ちの表（親が書く。パーツを書く Agent はこれと base.py を読んで、自分のファイルだけを書く）

<建物名>（OSM way <番号>）／写真: <パス>

## 約束
- 高さの基準: 地面 `c.G`、床 `c.F`（地面+1）、帯の段 `c.top`。接する部位は相手の基準で書く
- 位置: `parts.Facade(c, 面).at(k)`（外から見て左の角から k マス）。座標（x・z の数）を直書きしない
- 面の長さ（`python run.py <建物名> faces` の結果）: ★
- 質問の答え（フォームの1行）: ★
- 部位表: ★（部位・ブロックか飾りか・形・大きさ・位置（面と左の角から何マス）・高さの基準・向き）

## 受け持ち（1行 = 1 Agent = 1ファイル。並列に書く）
写真に無い部位の行は消す。看板は1枚ずつ、面は1面ずつ別の行にする。
型からコピーした `p_roof.py`・`p_band.py`・`p_sign_example.py` は書き方の例。受け持ちの Agent が上書きし、表に無い例のファイルは親が消す。

| ファイル | ORDER | 書く物 | 使う部品・型 | 渡す数（部位表から） |
|---|---|---|---|---|
| `p_roof.py` | 10 | 塔・屋上の柵 | `box_on_roof`・`lattice` | ★ |
| `p_band.py` | 15 | 帯と軒下の吊りランタン | `eave_slab` | ★ |
| `p_face_n.py` | 20 | 北の面（一部の窓・柱・帯の下の段・壁沿いの植え込み・車止め） | `window_strip`・`planter_ring`・`bollard` | ★ |
| `p_outside.py` | 30 | 外まわり（立て看板の足など。足は根元のマスから1本） | `c.put` | ★（立て看板は根元のマスと足の種類） |
| `p_sign_<名前>.py` | 40 | 看板1枚（位置・裏・絵） | `sign_art`（読んで描く） | ★ |
| `p_sign_poster.py` | 40 | 衝立のポスターの**絵だけ**（`images()` に `"poster"`。2×3。位置は組み立て役が置く） | `sign_art.shapes`（読んで描く） | ★ |

入口一式（衝立・通り道・植え込み・通路・扉・帯の延長・自動扉）と室内は、組み立て役が base.py の `ENTRANCE` から最後に置く（パーツに書かない）。

## 各 Agent に渡す依頼文（行ごとに <…> を埋める）
```text
building-remodel の建物のパーツを1つ書いてください。回答は日本語で。
■ 読む: tools/remodel/designs/<建物名>/plan.md と base.py、.claude/skills/building-remodel/parts.md（部品の早見表）、
  recipes.md の「<部位の見出し>」、写真 <パス>（<見る所: 例 北の面・左上の看板>）
■ 書く: tools/remodel/designs/<建物名>/<ファイル> だけ。受け持ち: <表の行をそのまま>
  ほかのファイル（base.py・plan.md・ほかのパーツ・parts.py などの道具）は書き換えない
■ 形: 型の例 designs/_parts_template/p_*.py と同じ（ORDER・part(c)・signs(geo, c)・BACKING・images() の使う物だけ）
■ 確かめ: cd tools/remodel して REMODEL_ONLY=<p_ を除いた名前> python run.py <建物名> preview <名前> と check。絵を1回見て、写真と比べる
■ 報告（短く）: 書いたファイル、置いた物の数を部位表の数と並べた表、迷った所
```

## 各 Agent の確かめ方
`REMODEL_ONLY=<p_ を除いた名前> python run.py <建物名> preview <名前>` で自分のパーツだけ描き、`check` を通す。
全員が終わったら、親が `python run.py <建物名> preview v1`（全部を組み立てた絵）・`section`・`check` を見る。
