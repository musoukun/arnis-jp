# GSI（国土地理院）データ統合 仕様書

## 概要

Arnisに国土地理院（GSI）のオープンデータを統合し、日本国内の建物・地形データを大幅に強化する機能。
OSMだけではカバーしきれない日本の住宅地の建物ポリゴンと、高精度な標高データを取得できる。

## データソース

| 項目 | 建物データ | 標高データ |
|------|-----------|-----------|
| 名称 | 最適化ベクトルタイル (optimal_bvmap) | 標高タイル (dem_png) |
| URL | `cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/{z}/{x}/{y}.pbf` | `cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png` |
| 形式 | Mapbox Vector Tile (Protobuf) | PNG (24bit符号付き整数) |
| レイヤー | `BldA`（建物ポリゴン） | — |
| ズームレベル | 16 | 10〜14 |
| 精度 | 建物フットプリント（個別ポリゴン） | 5m / 10m メッシュ |
| 認証 | 不要 | 不要 |
| 料金 | 無料 | 無料 |
| ライセンス | 出典明記（「国土地理院」） | 出典明記（「国土地理院」） |
| 更新頻度 | 四半期 | 不定期 |
| カバー範囲 | 日本全国 | 日本全国 |

出典: 国土地理院 (https://maps.gsi.go.jp/development/vt.html)

## 使い方

### CLI

```bash
# 建物データのみ（OSMとマージ）
cargo run -- --bbox "34.58,135.51,34.59,135.52" --gsi --output-dir "..."

# 建物 + 地形（GSI DEM使用）
cargo run -- --bbox "34.58,135.51,34.59,135.52" --gsi --terrain --output-dir "..."

# 従来通り（GSIなし）
cargo run -- --bbox "34.58,135.51,34.59,135.52" --output-dir "..."
```

### GUI

Settings画面の「GSI Buildings (Japan)」チェックボックスをONにする。

### 動作フロー

```
--gsi 指定時:

1. OSMデータ取得（Overpass API）     ← 従来通り
2. GSI建物タイル取得（PBF）          ← 追加
   - キャッシュあり → ローカルから読み込み
   - キャッシュなし → ダウンロード → キャッシュ保存
3. GSI建物をOSM形式に変換
4. OSMデータとマージ
5. パース → ワールド生成

--gsi + --terrain 指定時:
  標高データをAWS TerrariumではなくGSI DEMから取得
```

## 建物データ詳細

### 取得・変換パイプライン

```
bbox
  ↓ lat/lng → z=16 タイル番号計算
タイル一覧 (例: 4〜9枚)
  ↓ HTTP GET (キャッシュ優先)
PBFバイナリ
  ↓ prost でProtobufデコード
MVT Tile → BldA レイヤー抽出
  ↓ geometry コマンド解析 (MoveTo/LineTo/ClosePath)
タイルローカル座標 (0-4096)
  ↓ 緯度経度に変換
建物ポリゴン一覧
  ↓ bbox外の建物を除外（重心判定）
  ↓ OsmElement (node + way) に変換
OsmData
  ↓ OSMデータとマージ
統合データ → parse_osm_data() → ワールド生成
```

### 座標変換式

```
lng = (tile_x + pixel_x / extent) / 2^zoom * 360 - 180
lat = atan(sinh(π * (1 - 2 * (tile_y + pixel_y / extent) / 2^zoom))) * 180/π
```

### 建物タグ

| vt_code | 種別 | 付与タグ |
|---------|------|---------|
| 3101 | 普通建物 | `building=yes` |
| 3102 | 堅ろう建物 | `building=yes` |
| 3103 | 高層建物 | `building=yes`, `building:levels=5` |

全建物に `source=GSI optimal_bvmap` タグが付与される。

### ID体系

OSM本番IDとの衝突を避けるため、大きな値を使用:
- ノードID: `4,000,000,000` から連番
- ウェイID: `5,000,000,000` から連番

## 標高データ詳細

### デコード式

```
# GSI DEM PNG (24bit符号付き)
raw = R * 65536 + G * 256 + B
signed = raw >= 8388608 ? raw - 16777216 : raw
height_m = signed * 0.01

# 従来: AWS Terrarium
height_m = (R * 256 + G + B/256) - 32768
```

### GSI vs Terrarium 比較

| 項目 | GSI DEM | AWS Terrarium |
|------|---------|---------------|
| 精度 | 5m / 10m | 約30m |
| カバー | 日本のみ | 全世界 |
| 欠損処理 | alpha=0 で判定 | NaN補間 |
| 最大zoom | 14 | 15 |

### 選択ロジック

| `--gsi` | `--terrain` | 標高ソース |
|---------|-------------|-----------|
| なし | なし | フラット（標高なし） |
| なし | あり | AWS Terrarium |
| あり | なし | フラット（標高なし） |
| あり | あり | GSI DEM |

## キャッシュ

### 建物タイル

- 場所: `%LOCALAPPDATA%/arnis/gsi_tiles/16/{x}/{y}.pbf`（Windows）
- Linux: `~/.cache/arnis/gsi_tiles/16/{x}/{y}.pbf`
- macOS: `~/Library/Caches/arnis/gsi_tiles/16/{x}/{y}.pbf`
- 有効期限: なし（手動削除）

### 標高タイル

- 場所: `./arnis-tile-cache/gsi14_x{x}_y{y}.png`
- Terrarium: `./arnis-tile-cache/z{zoom}_x{x}_y{y}.png`
- 有効期限: 7日（自動削除）

### オフライン運用

事前にタイルをキャッシュフォルダに配置すれば、インターネット接続なしで動作する。

## 実測データ

### 北花田エリア（堺市）

| ソース | 建物数 |
|--------|------:|
| OSM単体 | 114棟 |
| GSI追加分 | 429棟 |
| **合計** | **543棟** |

広域（9タイル）:

| 指標 | 値 |
|------|---|
| タイル数 | 9 |
| GSI取得建物 | 7,152棟 |
| bbox内建物 | 4,043棟 |
| 全エレメント | 7,850 |

## 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `Cargo.toml` | `prost` 依存追加 |
| `src/gsi_data.rs` | **新規**: 建物タイル取得・キャッシュ・MVTデコード・OsmData変換 |
| `src/osm_parser.rs` | `OsmData`/`OsmElement` を crate 内公開、`merge()`/`from_elements()` 追加 |
| `src/elevation_data.rs` | GSI DEM URL・デコード式追加、`use_gsi` パラメータ |
| `src/ground.rs` | `use_gsi` フラグの引き回し |
| `src/args.rs` | `--gsi` フラグ追加 |
| `src/main.rs` | `mod gsi_data` + GSIデータマージロジック |
| `src/gui.rs` | `gsi_enabled` パラメータ追加 |
| `src/gui/index.html` | GSIチェックボックス追加 |
| `src/gui/js/main.js` | GSIトグル送信 |

## 制約・注意事項

- GSIデータは**日本国内のみ**。日本以外のbboxで `--gsi` を使うとタイルが404になり、建物0棟・標高欠損となる（エラーにはならない）
- OSMとGSIの建物が重複する場合、両方生成される（同じ場所に2つの建物が重なる）。実用上は問題なし（ブロックが上書きされるだけ）
- GSI建物には高さ情報がないため、Arnisのデフォルト高さ算出ロジックが適用される（vt_code=3103の高層建物のみ5階相当）
- 標高タイルの最大zoomは14（Terrariumは15）。非常に狭いエリアではTerrariumの方が解像度が高い場合がある
