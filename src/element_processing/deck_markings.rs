//! arnis-jp: lane paint on module bridge decks, drawn per carriageway from its OSM lanes.
//!
//! The deck schematics carry no paint of their own (see `bridge_modules`): one deck often
//! covers both carriageways of a dual road, so the lines follow each carriageway instead.
//! Solid edge lines on both sides, dashed lines between the lanes, as on a Japanese road.

use crate::block_definitions::*;
use crate::bresenham::bresenham_line;
use crate::element_processing::bridges::BridgeSurfaceMap;
use crate::element_processing::connected_blocks::stair_steps;
use crate::element_processing::highways::{highway_block_extent, lane_marking_count};
use crate::osm_parser::ProcessedWay;
use crate::world_editor::WorldEditor;

/// Deck street blocks a line may be painted on.
const PAINTABLE: &[Block] = &[CYAN_TERRACOTTA, GRAY_CONCRETE_POWDER];

/// Dash and gap length (metres) of a lane line; 5 m each on Japanese general roads.
const DASH_M: f64 = 5.0;

/// Paints `way`'s lane lines onto the deck surface below it.
pub fn paint_carriageway(
    editor: &mut WorldEditor,
    surface: &BridgeSurfaceMap,
    way: &ProcessedWay,
    scale: f64,
) {
    if way.tags.get("lane_markings").map(String::as_str) == Some("no") {
        return;
    }
    let highway = way.tags.get("highway").map(String::as_str).unwrap_or("");
    let lanes = lane_marking_count(highway, &way.tags);
    let (lo, hi) = highway_block_extent(highway, &way.tags, scale);
    // The road stamp runs -lo..=hi from the centre line, so its middle sits (hi - lo) / 2 off it.
    let shift = (hi - lo) as f32 / 2.0;
    let edge = (lo + hi) as f32 / 2.0;
    let lane_width = (lo + hi + 1) as f32 / lanes as f32;
    let dash = (DASH_M * scale).ceil().max(1.0) as usize;

    let mut prev_edges: [Option<(i32, i32)>; 2] = [None, None];
    let mut along = 0usize;
    for (n, pair) in way.nodes.windows(2).enumerate() {
        let (x1, z1, x2, z2) = (pair[0].x, pair[0].z, pair[1].x, pair[1].z);
        let (dx, dz) = ((x2 - x1) as f32, (z2 - z1) as f32);
        let len = (dx * dx + dz * dz).sqrt();
        if len == 0.0 {
            continue;
        }
        let (px, pz) = (-dz / len, dx / len);
        let at = |x: i32, z: i32, d: f32| {
            (
                (x as f32 + shift + px * d).round() as i32,
                (z as f32 + shift + pz * d).round() as i32,
            )
        };
        for (x, _, z) in bresenham_line(x1, 0, z1, x2, 0, z2)
            .into_iter()
            .skip((n > 0) as usize)
        {
            for (side, prev) in [-edge, edge].into_iter().zip(prev_edges.iter_mut()) {
                let cell = at(x, z, side);
                // Fill diagonal steps so the solid line stays unbroken.
                let cells = match *prev {
                    Some(p) if (p.0 - cell.0).abs() <= 2 && (p.1 - cell.1).abs() <= 2 => {
                        stair_steps(p, cell)
                    }
                    _ => vec![cell],
                };
                for (cx, cz) in cells {
                    paint(editor, surface, cx, cz);
                }
                *prev = Some(cell);
            }
            if along % (2 * dash) < dash {
                for l in 1..lanes {
                    let (cx, cz) = at(x, z, -edge - 0.5 + l as f32 * lane_width);
                    paint(editor, surface, cx, cz);
                }
            }
            along += 1;
        }
    }
}

/// Whitens the street block of the deck at (x, z), if there is one.
fn paint(editor: &mut WorldEditor, surface: &BridgeSurfaceMap, x: i32, z: i32) {
    let Some(deck_y) = surface.deck_y_at(x, z) else {
        return;
    };
    // On a ramp the resolved deck Y runs a few blocks above the street, so paint the top block.
    let Some(y) = (deck_y - DECK_Y_SLACK..=deck_y + 1)
        .rev()
        .find(|&y| editor.get_block_absolute(x, y, z).is_some())
    else {
        return;
    };
    editor.set_block_absolute(WHITE_CONCRETE, x, y, z, Some(PAINTABLE), None);
}

/// How far below the resolved deck Y the street row may sit.
const DECK_Y_SLACK: i32 = 4;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::args::Args;
    use crate::coordinate_system::cartesian::XZBBox;
    use crate::coordinate_system::geographic::LLBBox;
    use crate::element_processing::bridge_styles::BridgeOutlineIndex;
    use crate::element_processing::bridges::BridgeStructureMap;
    use crate::element_processing::highways::{generate_highways, TunnelPortalMap};
    use crate::floodfill_cache::{CoordinateBitmap, FloodFillCache};
    use crate::osm_parser::{ProcessedElement, ProcessedNode};
    use clap::Parser;
    use std::collections::{HashMap, HashSet};
    use std::path::PathBuf;

    fn way(id: u64, a: (i32, i32), b: (i32, i32)) -> ProcessedWay {
        let tags = [
            ("highway", "primary"),
            ("bridge", "yes"),
            ("layer", "1"),
            ("oneway", "yes"),
        ];
        ProcessedWay {
            id,
            nodes: [a, b]
                .iter()
                .enumerate()
                .map(|(i, &(x, z))| ProcessedNode {
                    id: id * 10 + i as u64,
                    tags: HashMap::new(),
                    x,
                    z,
                })
                .collect(),
            tags: tags
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        }
    }

    /// The Tokiwama line case: two 2-lane one-way carriageways side by side on one deck
    /// at world scale 1.4 get edge lines and one dashed lane line each, nothing else.
    #[test]
    fn dual_carriageway_deck_is_painted_per_carriageway() {
        let xzbbox = XZBBox::rect_from_xz_lengths(100.0, 100.0).unwrap();
        let llbbox = LLBBox::new(54.6, 9.9, 54.61, 9.91).unwrap();
        let mut editor = WorldEditor::new(PathBuf::from("/dev/null/unused"), &xzbbox, llbbox);
        let ground =
            crate::ground::Ground::new_elevation_test(vec![vec![0.0f32; 100]; 100], 100, 100);
        editor.set_ground(std::sync::Arc::new(ground));
        let args = Args::parse_from(["arnis", "--bbox", "1,2,3,4", "--scale", "1.4"].iter());
        let elems = vec![
            ProcessedElement::Way(way(1, (5, 40), (95, 40))),
            ProcessedElement::Way(way(2, (95, 50), (5, 50))),
        ];
        let outlines = BridgeOutlineIndex::build(&elems);
        let structures = BridgeStructureMap::build(&elems, &editor, &outlines, args.scale);
        let surface = BridgeSurfaceMap::build(&elems, &structures, args.scale);
        assert!(structures.lookup_member(1).unwrap().module_idx.is_some());
        let empty = CoordinateBitmap::new_empty();
        for elem in &elems {
            generate_highways(
                &mut editor,
                elem,
                &args,
                &HashMap::new(),
                &FloodFillCache::new(),
                &empty,
                &structures,
                &surface,
                &HashSet::new(),
                &TunnelPortalMap::default(),
                &empty,
                &mut Vec::new(),
            );
        }

        // Way 1 runs z 35..=46 (+z takes the extra block), way 2 runs z 45..=56.
        let solid = [35, 45, 46, 56];
        let dashed = [41, 51];
        let painted = |x: i32, z: i32| {
            (-10..=40)
                .any(|y| editor.check_for_block_absolute(x, y, z, Some(&[WHITE_CONCRETE]), None))
        };
        let mut dashed_seen = HashSet::new();
        for x in 25..=75 {
            for z in 33..=58 {
                if solid.contains(&z) {
                    assert!(painted(x, z), "edge line broken at ({x}, {z})");
                } else if dashed.contains(&z) {
                    if painted(x, z) {
                        dashed_seen.insert(z);
                    }
                } else {
                    assert!(!painted(x, z), "stray paint at ({x}, {z})");
                }
            }
        }
        assert_eq!(dashed_seen.len(), 2, "each carriageway has its lane line");
        // Dashes, not a solid line.
        assert!((25..=75).any(|x| !painted(x, 41)));
    }
}
