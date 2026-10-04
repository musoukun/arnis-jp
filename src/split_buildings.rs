//! arnis-jp: 1 つの建物が国土地理院の複数のポリゴンに分かれているとき、高さをそろえる。
//!
//! 例: イオンモール堺北花田は、OSM の外形 1 つの中に国土地理院の建物が「本体」と「先端」の
//! 2 つ入っている。どちらも高さの情報が無いので面積と乱数で別々に推定され、先端だけ低くなった。
//! PLATEAU が無くても動くよう、生成の前に OSM の外形ごとにかけらをまとめ、
//! - かけらのどれかに高さ（height / building:levels）があれば、一番高い値をほかのかけらにも付ける
//! - どれにも無ければ、全員を一番大きいかけらと同じ乱数・同じ面積で推定させる（同じ高さになる）
//!
//! 「体感リアルサイズ」の「分割建物の高さをそろえる」がオフなら何もしない。

use crate::building_height::footprint::{ring_area, ring_bounds, share_inside};
use crate::osm_parser::{PartGroups, ProcessedElement, ProcessedWay};

/// かけらがこの割合以上 OSM の外形の中にあれば、その建物のかけらとみなす
const MIN_SHARE_INSIDE: f64 = 0.6;

/// 推定に使う面積（マス）をこの値で上書きするタグ（buildings.rs の infer_building_height が読む）
pub const GROUP_AREA_TAG: &str = "arnis:group_area";

/// 高さの推定に 1 階あたり何 m とみなすか（building:levels しか無いかけらを比べるため）
const METERS_PER_LEVEL: f64 = 3.0;

fn ring(way: &ProcessedWay) -> Vec<(i32, i32)> {
    let mut r: Vec<(i32, i32)> = way.nodes.iter().map(|n| (n.x, n.z)).collect();
    if r.len() > 1 && r.first() == r.last() {
        r.pop();
    }
    r
}

fn is_building(way: &ProcessedWay) -> bool {
    way.tags.contains_key("building") && !way.tags.contains_key("building:part")
}

/// height（m）または building:levels から読んだ高さ（m）
fn known_height_m(way: &ProcessedWay) -> Option<f64> {
    if let Some(h) = way
        .tags
        .get("height")
        .and_then(|h| h.trim_end_matches('m').trim().parse::<f64>().ok())
        .filter(|h| h.is_finite() && *h > 0.0)
    {
        return Some(h);
    }
    way.tags
        .get("building:levels")
        .and_then(|l| l.trim().parse::<f64>().ok())
        .filter(|l| l.is_finite() && *l > 0.0)
        .map(|l| l * METERS_PER_LEVEL)
}

/// 生成の前に一度だけ呼ぶ。かけらの tags と part_groups を書き換える。
pub fn level_split_buildings(elements: &mut [ProcessedElement], part_groups: &mut PartGroups) {
    if !crate::perceived_size::fill_split_buildings() {
        return;
    }

    // (要素の位置, 輪郭, 外接矩形, 面積)
    let mut outlines = Vec::new();
    let mut pieces = Vec::new();
    for (i, el) in elements.iter().enumerate() {
        let ProcessedElement::Way(way) = el else {
            continue;
        };
        if !is_building(way) {
            continue;
        }
        let r = ring(way);
        let Some(b) = ring_bounds(&r) else {
            continue;
        };
        let area = ring_area(&r);
        if crate::gsi_data::is_gsi_way_id(way.id) {
            pieces.push((i, r, b, area));
        } else {
            outlines.push((i, r, b, area));
        }
    }

    // かけら → それを一番小さく包む OSM の外形
    let mut groups: Vec<Vec<usize>> = vec![Vec::new(); outlines.len()];
    for (pi, (_, pr, pb, parea)) in pieces.iter().enumerate() {
        let mut best: Option<(usize, f64)> = None;
        for (oi, (_, or, ob, oarea)) in outlines.iter().enumerate() {
            let overlaps = pb.0 <= ob.1 && ob.0 <= pb.1 && pb.2 <= ob.3 && ob.2 <= pb.3;
            if !overlaps || *oarea < *parea * 0.5 {
                continue;
            }
            if best.is_some_and(|(_, a)| a <= *oarea) {
                continue;
            }
            if share_inside(pr, or) >= MIN_SHARE_INSIDE {
                best = Some((oi, *oarea));
            }
        }
        if let Some((oi, _)) = best {
            groups[oi].push(pi);
        }
    }

    for members in &groups {
        // そろえる意味があるのは、かけらが 2 つ以上のときだけ
        if members.len() < 2 {
            continue;
        }
        let indices: Vec<usize> = members.iter().map(|&pi| pieces[pi].0).collect();
        let largest = members
            .iter()
            .copied()
            .max_by(|&a, &b| pieces[a].3.total_cmp(&pieces[b].3))
            .unwrap();
        let heights: Vec<Option<f64>> = indices
            .iter()
            .map(|&i| match &elements[i] {
                ProcessedElement::Way(w) => known_height_m(w),
                _ => None,
            })
            .collect();

        if let Some(max_m) = heights.iter().flatten().copied().reduce(f64::max) {
            // 高さを持つかけらがある: 一番高い値を、それより低い・持たないかけらに付ける
            for (&i, h) in indices.iter().zip(&heights) {
                if h.is_none_or(|h| h < max_m) {
                    if let ProcessedElement::Way(w) = &mut elements[i] {
                        w.tags.insert("height".to_string(), format!("{max_m}"));
                        w.tags.remove("building:levels");
                    }
                }
            }
        } else {
            // どれも高さを持たない: 一番大きいかけらと同じ乱数・同じ面積で推定させる
            let seed_way = match &elements[pieces[largest].0] {
                ProcessedElement::Way(w) => w.id,
                _ => continue,
            };
            let seed = part_groups.get(&seed_way).copied().unwrap_or(seed_way);
            let area = pieces[largest].3.round() as usize;
            let building_type = match &elements[pieces[largest].0] {
                ProcessedElement::Way(w) => w.tags.get("building").cloned(),
                _ => None,
            };
            for &i in &indices {
                if let ProcessedElement::Way(w) = &mut elements[i] {
                    part_groups.insert(w.id, seed);
                    w.tags.insert(GROUP_AREA_TAG.to_string(), area.to_string());
                    if let Some(t) = &building_type {
                        w.tags.insert("building".to_string(), t.clone());
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::osm_parser::ProcessedNode;
    use std::collections::HashMap;

    fn way(id: u64, rect: (i32, i32, i32, i32), tags: &[(&str, &str)]) -> ProcessedElement {
        let (x0, z0, x1, z1) = rect;
        let nodes = [(x0, z0), (x1, z0), (x1, z1), (x0, z1), (x0, z0)]
            .iter()
            .enumerate()
            .map(|(i, &(x, z))| ProcessedNode {
                id: id * 10 + i as u64,
                tags: HashMap::new(),
                x,
                z,
            })
            .collect();
        ProcessedElement::Way(ProcessedWay {
            id,
            nodes,
            tags: tags
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        })
    }

    fn tags_of(el: &ProcessedElement) -> &HashMap<String, String> {
        match el {
            ProcessedElement::Way(w) => &w.tags,
            _ => unreachable!(),
        }
    }

    const GSI: u64 = 5_000_000_000;

    // The AEON case: one OSM outline, a big GSI body and a GSI tip, no heights.
    #[test]
    fn untagged_pieces_share_the_largest_pieces_inference() {
        let mut els = vec![
            way(1, (0, 0, 100, 200), &[("building", "retail")]),
            way(GSI + 1, (0, 0, 100, 160), &[("building", "yes")]),
            way(GSI + 2, (0, 160, 100, 200), &[("building", "yes")]),
        ];
        let mut groups = PartGroups::new();
        level_split_buildings(&mut els, &mut groups);
        assert_eq!(groups.get(&(GSI + 1)), Some(&(GSI + 1)));
        assert_eq!(groups.get(&(GSI + 2)), Some(&(GSI + 1)));
        let area = tags_of(&els[1]).get(GROUP_AREA_TAG).cloned();
        assert!(area.is_some());
        assert_eq!(tags_of(&els[2]).get(GROUP_AREA_TAG).cloned(), area);
    }

    #[test]
    fn a_known_height_lifts_the_other_pieces() {
        let mut els = vec![
            way(1, (0, 0, 100, 200), &[("building", "retail")]),
            way(
                GSI + 1,
                (0, 0, 100, 160),
                &[("building", "yes"), ("height", "18")],
            ),
            way(
                GSI + 2,
                (0, 160, 100, 200),
                &[("building", "yes"), ("building:levels", "2")],
            ),
        ];
        level_split_buildings(&mut els, &mut PartGroups::new());
        assert_eq!(
            tags_of(&els[2]).get("height").map(String::as_str),
            Some("18")
        );
        assert!(!tags_of(&els[2]).contains_key("building:levels"));
    }

    #[test]
    fn a_lone_piece_or_an_outside_building_is_left_alone() {
        let mut els = vec![
            way(1, (0, 0, 100, 200), &[("building", "retail")]),
            way(GSI + 1, (0, 0, 100, 200), &[("building", "yes")]),
            way(GSI + 2, (300, 0, 400, 50), &[("building", "yes")]),
        ];
        let mut groups = PartGroups::new();
        level_split_buildings(&mut els, &mut groups);
        assert!(groups.is_empty());
        assert!(!tags_of(&els[1]).contains_key(GROUP_AREA_TAG));
    }
}
