# 参照（必要な時だけ読む）

[SKILL.md](SKILL.md) の手順の途中で、準備・トラブル・道具の一覧・正解例が要る時だけ開く。

## 準備
- ワールドは **縮尺 1.4** で生成する（法則1）:
  `arnis --bbox "<南,西,北,東>" --file <OSM JSON> --gsi --plateau --scale 1.4 --output-dir <出力>`。
  生成直後のワールドのコピーは捨てない（控えの追加に使う）。`world_mapping.json` の `scale` が 1.4 か確認する
- サーバー: `minecraft-server/`（1.21.11、RCON `127.0.0.1:25575` / `arnis2026`）。ユーザーのターミナルで起動する
  （Claude の裏の実行は2時間で止まる）: `cd D:\develop\arnis-jp\minecraft-server; java -Xms2G -Xmx8G -jar server.jar nogui`
- 1.21.11 のゲームルール名は新形式（昼の固定は `gamerule advance_time false`）

- **視野角**: `tools/remodel/view.json` の `fov`（既定 **102**、ユーザーの Minecraft の設定）。ゲーム内と比べる絵はこの値で描く。
  **ユーザーが視野角を指定したら `view.json` を書き換えて覚える**（次の建物でもその値を使う）。
  写真の視点に合わせるカメラだけは `CAMERAS` に `vfov` を書く（写真のレンズに合わせる）


## 躓きポイント（実際に踏んだもの）

| 症状 | 原因 | 対策 |
|---|---|---|
| ワールドを作り直したら座標がずれた | 設計ファイルに座標を直書き | 縮尺を変えたら座標も ×縮尺。なるべく建物のポリゴンからの相対で書く |
| 元の建物の屋根や柵が敷地の外に残る | 敷地の中しか消していなかった | 解体（つながっているブロックを追って消す）が `build` で自動で走る |
| 植え込みが1列しかない | 敷地を歩道から遠い所で切った | 敷地の端を歩道の手前まで広げる |
| 敷地を広げたら控えが無い | baseline は最初の敷地でしか撮っていない | `Construction.extend_baseline(生成直後のワールド)`。生成直後のワールドのコピーは捨てない |
| 施工したのにブロックが無い | 誰もいないとチャンクが読み込まれない | `builder.send()` が forceload する。`not loaded` は失敗として止まる |
| `Could not set the block` が大量 | 柵・鉄格子の「つながり方」だけ違う同じブロック | 失敗ではない（無視される） |
| 屋上の柵が写真より低く・薄く見える | 壁の真上に fence で立てた（帯の陰で1段隠れる、棒で軽い）、高さも低めに読んだ | [辞書](recipes.md)の「屋上の柵」（`parts.lattice`。段数は1階の高さとの比で、法則4） |
| 写真の視点の絵が天井だらけ／構造物の中 | カメラ位置の決め打ち | 真上の図で確認、候補を3つ描いて選ぶ |
| 地面が想定と違う | 地形ありの生成で地面が上がる | 地面は毎回測る（`run.py` の `detect_ground`） |
| 敷地外エラーで止まる | 軒や看板が隣の構造物に掛かった | 安全装置が正しく働いている。設計か `EXCLUDE` を直す |
| 葉が消える | 自然の葉は時間で消える | `persistent=true`（既定で付いている） |
| 地図アートを描き直しても変わらない | サーバーが地図をキャッシュする | 施工ごとに新しい地図 id（`run.py` が自動でやる） |
| ピストン・扉が動かない（置き直しても伸びない） | 誰もログインしていないとサーバーが時間を止める（`pause-when-empty-seconds=60`）。コマンドでブロックは置けるが仕掛けは動かない | 扉の試験は誰かがログインしている時に行う（`list` で確かめる） |
| 看板が正しい面に付いていない | 以前は額縁が西向きにしか置けず、看板を別の面へ移していた | `signs` の5番目に向きを書く（`north`/`south`/`east`/`west`）。プレビューにも看板の絵が出るので、向きと位置を絵で確かめる |
| `Unknown block type 'minecraft:chain'` | 1.21.9 で鎖の名前が変わった | `iron_chain`（ブロック名はサーバーの版で確かめる） |
| ピストンの扉が閉じない・開かない | 置く順番（通電より先にピストンを置くと縮んだまま） | `auto_door` を使う。`Blocks.ordered` で最後に置く。`run.py <建物> doortest` で試す |

---

## 性能の低いモデルで回すときのルール

- **モデルの仕事は3つだけ**: Step 2 の表を埋める、設計ファイルの値を置き換える、比較画像の違いを1つ言う

---

## 道具（tools/remodel/）

| ファイル | 役割 |
|---|---|
| `run.py` | 入口: `python run.py <設計名> preview|section|check|build|reset|capture|diff|doortest` |
| `ask_form.py` | 質問のフォームの型（質問の JSON → チャットに出すフォームの HTML） |
| `parts_ref.py` | 部品の早見表（parts.md）を parts.py から作り直す |
| `checks.py` | 施工の前の確かめ: `section`（断面の AA）、`inspect`（帯の下などの細長いすき間・足元に沈んだ看板・外から見えるレッドストーン） |
| `parts.py` | 部品ライブラリ: `build(spec, geo)`（床・壁・窓・ひさし・帯・屋根・看板の裏）、外まわりの部品、`entrance`（入れる入口。`steps="slab"` でハーフの段）、`planter_ring`・`eave_slab`・`lattice`・`box_on_roof`・`bollard`（部位の辞書の部品）、`sign_cells`（看板の向き）、`auto_door`（感圧板＋ピストンのガラス自動扉）、`furnish`（机・椅子・吊りランタン）、`louver`（屋上のルーバー）、`DEFAULT_PAL` |
| `scale.py` | （参考のみ）実寸 → マス数の換算。**部位の大きさを決めるのには使わない**（法則1: 目で見た比率と人の体で決める） |
| `block_catalog.py` | ブロックの色の対応表（全ブロックのテクスチャ・平均色・一番多い色と割合）と、写真の範囲 → 近いブロックを実物のテクスチャと並べる `match` |
| `view.json` | ユーザーの視野角（既定 102）。指定されたら書き換える |
| `map_art.py` | 地図アート（文字画像、減色、`world/data/` への書き出し） |
| `builder.py` | `Construction`: baseline の控え・`find_connected`/`add_demolition`（解体）・`extend_baseline`・`check_inside`・差分送信（forceload）・`place_frames`・`reset` |
| `parcel.py` | OSM のポリゴン → セル、外周、内側への距離 |
| `render.py` / `world_reader.py` / `block_colors.py` | 検証用の描画、リージョンファイルの読み込み、ブロックの平均色 |
| `designs/<建物>/` | 建物ごとの設計（パーツのフォルダ）。git に入れるのは型の `_parts_template/` と、サンプルの正解 `kfc_kitahanada_v2.py` だけ（ほかの建物の設計は管理外） |
`builds/`（控え・施工記録）と `out/`（プレビュー）はワールドごとのローカルデータで、git の管理外。
`builds/<建物>/baseline.json` は施工前の敷地の控えで、`reset` と解体に要るので消さない。

---

## 正解例: 写真 → 仕様の対応（ガスト 堺北花田）

| 写真から読んだこと | 仕様 |
|---|---|
| 平屋のファミレス、軒 3.7m（自転車の人 1.6m で測った） | `STACK = ["glass"]*3 + ["frame+awning", "band"]`（柱5マス = 店舗1階の最低） |
| 寄棟の屋根、高さ 約1.8m | `ROOF = {"type": "hip", "rise": 2.5}`（頂部 約8マス） |
| 窓は西・北・南。東は写っていない | `WINDOW_FACES = {"w","n","s"}` |
| 南西が凹んだ入口ポーチ（屋根付き） | `footprint` で凹みを屋根に含める、`DOOR_FACE = "w"` |
| 赤い帯、赤白の縞のひさし | `band` = `red_concrete`、`awning` = 赤白のウール |
| 窓の柱間（写真で見て窓1枚がやや横長） | `PILLAR_EVERY = 4` |
| 屋根正面の「レストラン ガスト」、ポール看板、縦看板「から好し」 | 地図アート 8×1 / 3×3＋3×1 / 1×3（屋根の幅・人の背丈と比べて決めた）、裏は黒・赤・白のブロック |
| レンガの植え込みと生け垣、のぼり4本、駐輪ラック3、電柱、店先のタイル、点字ブロック | `extras` で `planter`・`nobori`・`bike_racks`・`pole`・`ground` |
