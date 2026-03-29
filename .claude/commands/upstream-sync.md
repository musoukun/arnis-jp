# upstream-sync: 本流arnis最新変更の取り込み

upstream（louis-e/arnis）の最新変更をarnis-jpのmainブランチに取り込み、ビルド検証してpushするワークフロー。

## 前提条件

- 作業ディレクトリ: `D:\develop\arnis-jp`
- upstream remote: `https://github.com/louis-e/arnis.git`
- origin remote: `https://github.com/musoukun/arnis-jp.git`
- マージ先: `main` ブランチ

## ワークフロー

以下のステップを順番に実行すること。途中でエラーが発生した場合は、そのステップで止まってユーザーに報告する。

### Step 1: 事前チェック

```bash
cd /d/develop/arnis-jp
```

1. `git status` で未コミットの変更がないか確認。あれば**中断してユーザーに報告**
2. `git branch --show-current` で現在のブランチを確認
3. 現在のブランチが `main` でなければ `git checkout main` で切り替え
4. `git pull origin main` でorigin最新を取得

### Step 2: upstreamの変更確認

1. `git fetch upstream` でupstreamの最新を取得
2. `git log main..upstream/main --oneline` で未取り込みコミットを一覧表示
3. コミットがない場合は「最新です、取り込む変更はありません」と報告して**終了**
4. コミットがある場合、変更内容の要約をユーザーに表示:
   - コミット数
   - 主な変更ファイル（`git diff main..upstream/main --stat`）
   - 重要な変更の概要（新機能、バグ修正、破壊的変更など）

### Step 3: マージ

1. `git merge upstream/main` を実行
2. **コンフリクトが発生した場合:**
   - コンフリクトファイルを一覧表示
   - arnis-jpのカスタマイズ箇所（下記「保護すべきファイル」参照）はarnis-jp側を優先
   - upstream側の新機能追加はupstream側を取り込み
   - 判断が難しい場合はユーザーに確認
   - 全コンフリクト解決後 `git add` して `git commit`

### Step 4: arnis-jp固有の整合性チェック

マージ後、以下のarnis-jp固有の変更が壊れていないか確認する:

1. **モジュール参照の整合性**: `src/main.rs` に `mod building_metadata` や `mod world_mapping` など、arnis-jp側に存在しないモジュールへの参照が追加されていないか確認。あれば削除
2. **GenerationOptions構造体**: `src/data_processing.rs` の `GenerationOptions` と `src/main.rs`/`src/gui.rs` での使用箇所が一致しているか確認
3. **日本語ローカライゼーション**: `src/gui/locales/ja.json` が存在し、`src/gui/index.html` の言語セレクタに日本語オプションがあるか確認
4. **カスタムURL**: 以下がmusoukun/arnis-jpを指しているか確認:
   - `Cargo.toml` の `homepage` と `repository`
   - `src/gui/js/main.js` のアップデートリンク
   - `src/gui/index.html` のフッターリンク
5. **初期マップ位置**: `src/gui/js/bbox.js` の `setView` が東京スカイツリー座標 `[35.7101, 139.8107]` になっているか確認
6. **en-US.jsonの新キー**: upstreamで `en-US.json` に新しいキーが追加された場合、`ja.json` にも対応する日本語翻訳を追加
7. **新しいtooltip**: `index.html` に新しい `data-tooltip` 属性が追加された場合、`data-tooltip-key` 属性も追加し、`ja.json` と `en-US.json` にキーを追加

問題があれば修正してコミットする。

### Step 5: ビルド検証

```bash
cargo build --release 2>&1
```

1. エラーがあれば修正してコミット
2. warningは許容（未使用importなど軽微なもの）
3. ビルドが成功するまで繰り返す

### Step 6: push

1. `git push origin main` でpush
2. 結果をユーザーに報告:
   - 取り込んだコミット数
   - 主な変更内容
   - 修正が必要だった箇所（あれば）
   - ビルド結果

## 保護すべきファイル（arnis-jp固有のカスタマイズ）

コンフリクト時、以下のファイルはarnis-jp側の変更を優先的に保護する:

| ファイル | 保護内容 |
|---------|---------|
| `Cargo.toml` | homepage, repository URL |
| `src/gui/locales/ja.json` | 日本語翻訳ファイル全体 |
| `src/gui/index.html` | 日本語オプション、フッターURL、data-tooltip-key属性 |
| `src/gui/js/main.js` | アップデートリンクURL、tooltip/satellite_colors/gsi_buildingsローカライゼーション |
| `src/gui/js/bbox.js` | 初期マップ位置（東京スカイツリー） |
| `src/gui/locales/en-US.json` | 追加したtooltipキー、satellite_colors、gsi_buildingsキー |

upstreamがこれらのファイルに新機能を追加した場合は、arnis-jpのカスタマイズを維持しつつ新機能も取り込む（両方活かす）。

## upstreamが新しいローカライゼーションキーを追加した場合

1. `en-US.json` の差分から新キーを特定
2. 各キーの英語テキストを元に日本語訳を作成
3. `ja.json` に追加
4. tooltip関連の場合は `index.html` の対応する要素にも `data-tooltip-key` 属性を追加
