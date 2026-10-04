//! arnis-jp: 「体感リアルサイズ」の各調整。
//!
//! Minecraft のプレイヤーから見て実物らしい大きさに感じるよう、arnis-jp が
//! upstream から変えている寸法。項目ごとにオン/オフ（高架は高さ）を選べる。
//!
//! - 道路の幅: ワールド倍率が 1 より大きいとき「倍率 − 0.1」倍（1.4 なら 1.3 倍）
//! - 高架の高さ: 1 層ぶんの段差・桁下・重なる橋の間（upstream は 6 ブロック）
//! - 自転車置き場: 屋根・柱・壁を作らず床だけ
//! - 分割建物: 1 つの建物が複数ポリゴンに分かれているとき、低い側（イオンモールの
//!   先端などのいびつな部分）を大きい側の高さにそろえる
//!
//! 建物の幅・奥行き・高さはもともとワールド倍率どおりに広がるので、ここでは扱わない。
//! 道路・高架などの処理の奥まで引数を通さずに済むよう、生成の始めに一度だけ
//! `configure` で設定し、各処理は関数で値を読む。

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};

/// upstream arnis の高架の段差・桁下
pub const UPSTREAM_ELEVATED_HEIGHT: i32 = 6;

// 既定は CLI と同じ（すべてオン、高架 8）。テストもこの値で動く。
static WIDE_ROADS: AtomicBool = AtomicBool::new(true);
static ELEVATED_HEIGHT: AtomicI32 = AtomicI32::new(8);
static BARE_BICYCLE_PARKING: AtomicBool = AtomicBool::new(true);
static FILL_SPLIT_BUILDINGS: AtomicBool = AtomicBool::new(true);

/// 生成を始める前に、CLI / GUI の設定を一度だけ反映する
pub fn configure(args: &crate::args::Args) {
    WIDE_ROADS.store(args.wide_roads, Ordering::Relaxed);
    ELEVATED_HEIGHT.store(args.elevated_height, Ordering::Relaxed);
    BARE_BICYCLE_PARKING.store(args.bare_bicycle_parking, Ordering::Relaxed);
    FILL_SPLIT_BUILDINGS.store(args.fill_split_buildings, Ordering::Relaxed);
}

/// 高架 1 層ぶんの高さ、道路の上の桁下、上下に重なる橋の間（すべて同じ値）
pub fn elevated_headroom() -> i32 {
    ELEVATED_HEIGHT.load(Ordering::Relaxed)
}

/// 道路の半幅に掛ける倍率。ワールド倍率が 1 以下なら upstream どおり（ここでは 1.0）。
pub fn road_width_factor(scale: f64) -> f64 {
    if WIDE_ROADS.load(Ordering::Relaxed) && scale > 1.0 {
        (scale - 0.1).max(1.0)
    } else {
        1.0
    }
}

/// 屋根・柱・壁を省いて床だけにする自転車置き場か
pub fn bare_bicycle_parking(tags: &HashMap<String, String>) -> bool {
    BARE_BICYCLE_PARKING.load(Ordering::Relaxed)
        && (tags.get("amenity").map(String::as_str) == Some("bicycle_parking")
            || tags.contains_key("bicycle_parking"))
}

/// 分割された建物の低い側を、大きい側の高さにそろえるか
pub fn fill_split_buildings() -> bool {
    FILL_SPLIT_BUILDINGS.load(Ordering::Relaxed)
}
