# 部品の早見表（parts.py）

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

### `building_cells(geo, way, scale=0.9285714285714287)`

OSM の建物の形（ワールドの縮尺 1.4）を、真ん中を中心に scale 倍に縮めてマスにする。設計の footprint(geo) で使う。

### `grow_footprint(cells, shift=(0, 0), grow=None, straighten=())`

OSM の建物の形（セルの集合）を、再現に合わせて整える。設計の footprint(geo) から呼ぶ。
  shift: (東へ, 南へ) ずらすマス数（負なら西・北）。正面の前に通り道・衝立・植え込みの余裕を作る時に
  grow: {"n": 2, "s": 1, ...} その面を外へ何マス広げるか（各列・各行の端から伸ばす）。ワールドは縮尺 1.4 なので、
        比率に合わせて数マス広げてよい（法則1）
  straighten: ("n", "w", ...) その面の1〜2マスの段（OSM の傾き・ずれ）を、一番外の線までそろえて1本の真っすぐな壁にする
戻り値: 整えたセルの集合

### `Facade(c, face)`

建物の1つの面を「外から見て左の角から何マス」で指す。質問の答え（「北の角から10マス」）をそのまま書ける。
face: "n"/"s"/"w"/"e"。外から見て左の角が k=0（西面なら北の角、北面なら東の角）、右へ k が増える。
角は、その面で一番長くまっすぐ続く壁の線の端（建物が L 字などでも、正面の線で数える）。
  at(k, out=0) … 左の角から k マス目の壁のセル（その列で一番外の壁。線の外の k や負の k も指せる）。out マス外へ出たセル
  width        … 正面の線の長さ。真ん中は width // 2
例: west = parts.Facade(c, "w"); door = [west.at(10), west.at(11)]; 衝立 = west.at(10, out=2)

### `planter(c, cells, hedge_second_row=0.6)`

レンガの縁（1マス）＋生け垣（1段目は全部、2段目は割合）。窓とひさしを隠さないよう2段まで。

### `small_tree(c, x, z, allowed)`

幹2段＋頭に葉（高さ 3 マス）。allowed（植え込みのセル）の中だけ。

### `nobori(c, spots, rotation=4, color='white', accent='red')`

のぼり旗: 柵の柱の上に模様付きの旗（高さ約3マス）。rotation 4 = 西向き。

### `bike_racks(c, spots)`



### `louver(c, height, avoid=(), material='dark_oak_trapdoor')`

屋上の柵・ルーバー。軒先の輪（帯の上）に、外側の面に板を立てる（開いたトラップドア）。
壁の真上だと帯の張り出しで下の段が隠れ、柵（fence）は棒なので軽く見える。avoid（塔など）に接する所は空ける。

### `pole(c, x, z, height, material=None)`

柱（電柱は 12 マス、看板の柱など）。

### `ground(c, cells, material)`

舗装の張り替え（店先のタイル・点字ブロックなど）。軒の下は除く。

### `entrance(c, cells, face, height=3, out=2, inside=2, steps='stairs', step_slab='brick_slab')`

入れる入口を作る（どの建物でも extras の最後に呼ぶ）。
cells: 入口にする壁のセル、face: 外を向いた面（"n"/"s"/"w"/"e"）。
- 床: 室内・開口は床の高さ F。土台（PLINTH）があれば、外側に段を置いて上がれるようにする
  steps="stairs": 階段ブロックで1マスずつ（従来）。steps="slab": ハーフずつ上がる（辞書の「入口の段」）
  steps="landing": 扉の前の1マスだけフルブロック（床の高さ）、その外はハーフずつ下がる（よく使う作り。辞書の「扉の前の踏み台」）
- 開口: 床から高さ height（店舗 3、住宅 2）。壁と、奥に引っ込めた窓の列の両方を開ける
- 通り道: 外側 out マス・内側 inside マスは、頭の高さまで障害物を消す
プレイヤーは高さ 1.8、ジャンプで上がれるのは約 1.25。上枠は「床 + height」より下に置かない。

### `window_strip(c, face, k0, k1, rows=3, glass=None, recess=True, mullion=None)`

面の一部だけを窓にする（ほかは壁のまま）。face の面の、左の角から k0〜k1 マス目に、床の上から rows 段のガラス。
recess: ガラスを1マス奥に引っ込める（上下の枠の影が出る）。mullion: 細い縦枠を入れる k のリスト（黒い板ガラス）。

### `front_entrance(c, face, door_k, screen_k=None, screen_w=4, left_gap=3, right_gap=1, bed_end=6, band='mangrove_slab', walk='brick_slab', landing='bricks', bed_edge='brick_wall', bed_fill='diorite', screen_edge='deepslate_brick_wall', screen_core='deepslate_bricks', bollard_post='blackstone_wall', light='lantern', auto=True)`

入口のまわり一式（辞書「入口のまわり」「扉の前の踏み台」）。extras の最後に1回呼ぶだけで、次を正しい順で置く:
  通り道（壁の1マス外、ハーフ）・衝立（壁の2マス外、両端と上は塀、上は帯の真下まで。帯とは別で塔にはつながない）・
  衝立の前を通る植え込み（塀・砂利・塀、壁の3マス外が砂利）・左右の通路（植え込みを切ってハーフ）・
  右の端を建物まで閉じる塀・車止め（衝立の両脇と右の植え込みの真ん中、黒い塀＋ランタン）・
  扉（entrance、扉の前の1マスだけフルブロック）・帯の延長（衝立の上まで）・ガラスの自動扉（auto_door）。
face: 入口の面。位置は Facade と同じ「外から見て左の角から k マス」（左の角が 0）。
  door_k: 扉（2マス）の左のマス。screen_k: 衝立の左の端（省略すると door_k-1）。screen_w: 衝立の幅
  left_gap / right_gap: 衝立と左／右の通路のあいだの植え込みのマス数。bed_end: 衝立の右の端から、右の端の塀まで何マス
  band: 衝立の上まで前に出す帯のハーフ（None なら帯を前に出さない）。auto: ガラスの自動扉にするか（False なら開口のまま）
戻り値: {"door": 扉の壁セル2つ, "used": auto_door の戻り値（furnish の avoid に渡す）,
        "poster": signs に足す衝立のポスター（"poster", 列, 行, 左上の額縁, 向き）, "bed": 植え込みの砂利のセル}
（PLINTH = 1 の建物用。辞書「入口のまわり」の作り）

### `entrance_poster(c, face, door_k, screen_k=None, screen_w=4)`

front_entrance の衝立のポスターの看板（"poster", 列, 行, 左上の額縁, 向き）。設計の signs(geo) に足す。
裏は衝立の芯（SIGN_BACKING の "poster" は screen_core と同じ deepslate_bricks に）。

### `camera(c, face, k, out, look_k=None, height=1.6, pitch=-6, **kw)`

プレビューのカメラを、座標を書かずに置く: face の面の左の角から k マス・壁から out マス外、目の高さ height。
look_k（省略すると k）の壁の所を向く。k を面の外（負や width 以上）にすると斜めの視点になる。
base.py の cameras(c) で {"名前": parts.camera(...)} を返す（run.py が使う）。

### `furnish(c, faces, avoid=(), every=4)`

正面から見える室内: 窓の面の内側に机（柵＋感圧板）と椅子（階段）、天井に吊ったランタン。
窓の面の壁から 2・3・4 マス内側に「椅子・机・椅子」を every マスおきに並べる。avoid（入口・仕掛け）は空ける。

### `auto_door(c, cells, face)`

感圧板で開くガラスの自動扉（幅2・高さ2）。入口は「柱に挟まれた凹み」: 壁の線の左右2マスずつを柱にし、
その1マス奥にガラスの扉。仕掛け（ピストン・トーチ・粉）は石レンガで包み、配線は床下・トーチは床の中に隠す。
仕組み: 粘着ピストンが左右から扉のガラスを押し出して閉じている（レッドストーントーチの常時信号）。
感圧板を踏むと床下の配線でトーチが消え、ピストンが縮んでガラスを壁の中へ引き込む＝開く。
配線は床下（F-1）に通すので PLINTH >= 1 が必要。cells は入口の壁セル2つ、face は外を向いた面。
戻り値: 仕掛けと通り道のセル（furnish の avoid に渡す）。

### `planter_ring(c, select, edge='brick_wall', fill='diorite')`

植え込み: 建物の壁に沿わせる。壁のすぐ外の1マスに砂利（fill）、その外側を細いレンガの塀（edge）で囲う。
select(セル) が真の「壁のすぐ外のセル」が砂利になる。端も塀で閉じる。高さは1マス。
壁から離して歩道の上に置かない（植え込みは建物の足元にある）。戻り値: (砂利のセル, 塀のセル)

### `eave_slab(c, slab='mangrove_slab', lantern_every=4, faces=None)`

帯（軒）: 壁から1マス張り出した **ハーフブロック**（下付き）。フルブロックにしない（帯は薄い）。
軒下に吊りランタンを lantern_every マスおき（faces の面だけ。看板などが既にある所は置かない）。
赤いコンクリートにハーフは無いので、赤系のハーフ（mangrove_slab 等）を使う。

### `lattice(c, height=3, bars='nether_brick_fence', skip=())`

屋上の格子: 屋根の縁（壁の真上）に柵を height 段積む。柵は横につながって横棒になり、向こうが透ける。

### `box_on_roof(c, cells, height, material)`

屋上に載る箱（看板の塔など）。cells の上に height 段。

### `bollard(c, spots, y, post='polished_blackstone_wall', light='lantern')`

車止め・足元灯: 黒い塀のブロックの上にランタン（辞書の「柱の上の明かり・車止め」。y は塀の段）。
