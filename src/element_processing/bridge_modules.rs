//! Swept modular bridge decks built from bundled segment schematics.

use std::collections::HashMap;
use std::sync::OnceLock;

use crate::block_definitions::*;
use crate::element_processing::bridge_footprint::DeckClip;
use crate::element_processing::bridge_styles::{side_faces_open, BridgePathSample};
use crate::element_processing::bridges::BridgeSurfaceMap;
use crate::structures::schematic::{load_structure, rotate_props};
use crate::world_editor::WorldEditor;

static SEG1: &[u8] = include_bytes!("../../assets/structures/bridge_segment_1.schem");
static SEG2: &[u8] = include_bytes!("../../assets/structures/bridge_segment_2.schem");
static SEG3: &[u8] = include_bytes!("../../assets/structures/bridge_segment_3.schem");
static SEG4: &[u8] = include_bytes!("../../assets/structures/bridge_segment_4.schem");

/// Voxels this far below the street row count as pillar feet.
const PILLAR_FOOT_MIN_DEPTH: i32 = 3;
/// Cap for extending pillar feet down to the terrain, enough for tall viaducts.
const PILLAR_GROUND_FILL_LIMIT: usize = 512;
/// Bridges shorter than this keep the procedural rendering.
const MIN_MODULE_BRIDGE_LEN: usize = 12;

pub struct BridgeModule {
    length: usize,
    half_width: i32,
    // Outermost column on the +w side and (as a distance) on the -w side; an even-width
    // schematic reaches one column further on the -w side.
    edge_pos: i32,
    edge_neg: i32,
    slices: Vec<Vec<(i32, i32, BlockWithProperties)>>,
    feet: Vec<Vec<(i32, i32, BlockWithProperties)>>,
    has_pillars: bool,
}

/// Blocks allowed to form ground-extended pillar shafts.
fn is_pillar_material(block: Block) -> bool {
    matches!(
        block,
        SANDSTONE
            | SMOOTH_SANDSTONE
            | SANDSTONE_WALL
            | STONE
            | STONE_BRICKS
            | ANDESITE
            | ANDESITE_WALL
            | COBBLESTONE
            | SMOOTH_STONE
    )
}

/// Slices a segment schematic along X into per-length cross-sections centred on the street row.
fn build_module(bytes: &'static [u8], street_y: i32, has_pillars: bool) -> Option<BridgeModule> {
    let schem = match load_structure(bytes) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("bridge segment load failed: {e}");
            return None;
        }
    };
    let length = schem.width.max(1) as usize;
    let center_w = schem.length / 2;

    let mut slices = vec![Vec::new(); length];
    for (x, y, z, block) in schem.voxels {
        // Under-deck stud buttons double up where ramp steps overlap; drop them.
        if block.block == STONE_BUTTON && y < street_y {
            continue;
        }
        if let Some(slice) = slices.get_mut(x as usize) {
            slice.push((z - center_w, y - street_y, block));
        }
    }

    let mut feet = vec![Vec::new(); length];
    if has_pillars {
        for (l, slice) in slices.iter().enumerate() {
            let mut lowest: HashMap<i32, (i32, BlockWithProperties)> = HashMap::new();
            for (w, dy, block) in slice {
                // Only solid shaft material may extend down; attachments would dangle.
                if !is_pillar_material(block.block) {
                    continue;
                }
                match lowest.get(w) {
                    Some((cur, _)) if *cur <= *dy => {}
                    _ => {
                        lowest.insert(*w, (*dy, block.clone()));
                    }
                }
            }
            for (w, (dy, block)) in lowest {
                if dy <= -PILLAR_FOOT_MIN_DEPTH {
                    feet[l].push((w, dy, block));
                }
            }
        }
    }

    let columns = || slices.iter().flatten().map(|(w, _, _)| *w);
    let edge_pos = columns().max().unwrap_or(0).max(0);
    let edge_neg = (-columns().min().unwrap_or(0)).max(0);

    Some(BridgeModule {
        length,
        half_width: schem.length / 2,
        edge_pos,
        edge_neg,
        slices,
        feet,
        has_pillars,
    })
}

fn modules() -> &'static Vec<BridgeModule> {
    static CELL: OnceLock<Vec<BridgeModule>> = OnceLock::new();
    CELL.get_or_init(|| {
        [
            (SEG1, 8, true),
            (SEG2, 16, true),
            (SEG3, 2, false),
            (SEG4, 3, false),
        ]
        .into_iter()
        .filter_map(|(bytes, street_y, pillars)| build_module(bytes, street_y, pillars))
        .collect()
    })
}

/// Picks the narrowest deck module that still covers the road with margin.
pub fn pick_module_index(block_range: i32, bridge_len: usize) -> Option<usize> {
    if bridge_len < MIN_MODULE_BRIDGE_LEN || modules().len() < 4 {
        return None;
    }
    Some(if block_range >= 6 {
        0
    } else if block_range == 5 {
        if bridge_len >= 45 {
            1
        } else {
            2
        }
    } else {
        3
    })
}

pub fn module_at(idx: usize) -> Option<&'static BridgeModule> {
    modules().get(idx)
}

pub fn module_half_width(idx: usize) -> Option<i32> {
    modules().get(idx).map(|m| m.half_width)
}

/// Half-width of the widest bundled deck.
pub fn max_module_half_width() -> i32 {
    modules().iter().map(|m| m.half_width).max().unwrap_or(0)
}

/// Columns at a deck edge (kerb, parapet) kept whole when the deck is cut narrower.
const EDGE_BAND: i32 = 2;

/// Where cross-section column `w` lands on a deck reaching `edge` columns out on its side, cut
/// to `limit`, or None when it falls in the cut. The edge band is shifted in so the parapet stays.
fn clip_column(w: i32, limit: i32, edge: i32) -> Option<i32> {
    if limit >= edge {
        return Some(w);
    }
    let limit = limit.max(EDGE_BAND + 1);
    let a = w.abs();
    if a >= edge - EDGE_BAND {
        Some(w.signum() * (limit - (edge - a)))
    } else if a < limit - EDGE_BAND {
        Some(w)
    } else {
        None
    }
}

/// Quarter turns from the module's native +X axis to the sample's path direction.
fn direction_quarter_turns(px: f32, pz: f32) -> u8 {
    // perp = (-uz, ux), so the unit direction is (pz, -px).
    let (ux, uz) = (pz, -px);
    if ux.abs() >= uz.abs() {
        if ux >= 0.0 {
            0
        } else {
            2
        }
    } else if uz >= 0.0 {
        1
    } else {
        3
    }
}

/// Rotates a block's direction-carrying properties by `k` quarter turns.
fn rotated_block(block: &BlockWithProperties, k: u8) -> BlockWithProperties {
    if k == 0 {
        return block.clone();
    }
    match &block.properties {
        Some(props) => BlockWithProperties::new(block.block, Some(rotate_props(props, k))),
        None => block.clone(),
    }
}

/// Road surface of every bundled deck segment.
const MODULE_STREET_BLOCK: Block = CYAN_TERRACOTTA;

/// Road surface and lane paint on a segment's street row.
fn is_street_block(block: Block) -> bool {
    block == MODULE_STREET_BLOCK || block == WHITE_CONCRETE
}

/// Parapets, posts and signs along a deck edge.
fn is_railing_part(block: Block) -> bool {
    let name = block.name();
    [
        "_wall",
        "_fence",
        "_fence_gate",
        "_bars",
        "_sign",
        "_button",
        "_trapdoor",
        "_pane",
        "lantern",
    ]
    .iter()
    .any(|suffix| name.ends_with(suffix))
        || name.contains("chain")
}

/// Sweeps the module cross-sections along the bridge path, tiling by path index.
pub fn sweep_module(
    editor: &mut WorldEditor,
    surface: &BridgeSurfaceMap,
    path: &[BridgePathSample],
    module: &BridgeModule,
    clip: Option<&DeckClip>,
) {
    // Deck reach (left, right) per sample; the full half-width unless the outline cuts it.
    let limits: Vec<(i32, i32)> = path
        .iter()
        .map(|&(x, _, z, (px, pz))| match clip {
            Some(c) => (
                c.reach_along(x, z, (px, pz), module.half_width),
                c.reach_along(x, z, (-px, -pz), module.half_width),
            ),
            None => (module.half_width, module.half_width),
        })
        .collect();

    let (mut open_left, mut open_right) = (0usize, 0usize);
    for (&(x, deck_y, z, (px, pz)), &(lim_left, lim_right)) in path.iter().zip(&limits) {
        for (sign, count, lim) in [
            (1.0f32, &mut open_left, lim_left),
            (-1.0, &mut open_right, lim_right),
        ] {
            // Where the deck's square footprint ends along the perpendicular.
            let edge = lim as f32 * (px.abs() + pz.abs()) + 1.0;
            let cell = (
                (x as f32 + px * sign * edge).round() as i32,
                (z as f32 + pz * sign * edge).round() as i32,
            );
            *count += side_faces_open(surface, cell, (px * sign, pz * sign), deck_y) as usize;
        }
    }
    let open_left = open_left * 2 >= path.len();
    let open_right = open_right * 2 >= path.len();
    let concrete = module.has_pillars && crate::perceived_size::concrete_piers();

    for (i, &(x, deck_y, z, (px, pz))) in path.iter().enumerate() {
        let (lim_left, lim_right) = limits[i];
        // (reach, outermost column) on the side of column `w`.
        let side_for = |w: i32| {
            if w > 0 {
                (lim_left, module.edge_pos)
            } else {
                (lim_right, module.edge_neg)
            }
        };
        let k = direction_quarter_turns(px, pz);
        let cell = |w: i32| {
            (
                (x as f32 + px * w as f32).round() as i32,
                (z as f32 + pz * w as f32).round() as i32,
            )
        };
        // On diagonals a slice skips every other cell; fill the step towards the centre.
        let cells = |w: i32| {
            let (bx, bz) = cell(w);
            let inner = cell(w - w.signum());
            if w != 0 && inner.0 != bx && inner.1 != bz {
                vec![(bx, bz), (bx, inner.1)]
            } else {
                vec![(bx, bz)]
            }
        };
        let slice = &module.slices[i % module.length];
        for (w, dy, block) in slice {
            let open = if *w > 0 { open_left } else { open_right };
            // No railing against another deck.
            if !open && *dy > 0 && w.abs() * 2 >= module.half_width {
                continue;
            }
            if !open && *dy == 0 && is_railing_part(block.block) {
                continue;
            }
            // Its kerb becomes road, so the decks read as one carriageway.
            let kerb = !open
                && *dy == 0
                && w.abs() >= module.half_width - 2
                && !is_street_block(block.block);
            let (limit, edge) = side_for(*w);
            let Some(col) = clip_column(*w, limit, edge) else {
                continue;
            };
            for (bx, bz) in cells(col) {
                if kerb {
                    editor.set_block_absolute(MODULE_STREET_BLOCK, bx, deck_y, bz, None, None);
                    continue;
                }
                if *dy <= -PILLAR_FOOT_MIN_DEPTH && surface.support_blocked(bx, bz, deck_y) {
                    continue;
                }
                // arnis-jp: the schematic's pier shaft gives way to a concrete column below.
                if concrete
                    && *dy <= -PILLAR_FOOT_MIN_DEPTH
                    && is_pillar_material(block.block)
                {
                    continue;
                }
                editor.set_block_with_properties_absolute(
                    rotated_block(block, k),
                    bx,
                    deck_y + dy,
                    bz,
                    None,
                    Some(&[]),
                );
            }
        }
        if module.has_pillars {
            for (w, dy, block) in &module.feet[i % module.length] {
                let (limit, edge) = side_for(*w);
                let Some(col) = clip_column(*w, limit, edge) else {
                    continue;
                };
                for (bx, bz) in cells(col) {
                    if surface.support_blocked(bx, bz, deck_y) {
                        continue;
                    }
                    let ground = editor.get_ground_level(bx, bz);
                    if concrete {
                        // arnis-jp: one grey concrete column from under the pier cap to the
                        // ground, whatever the deck height.
                        let top = deck_y - PILLAR_FOOT_MIN_DEPTH;
                        for y in (ground..=top).rev().take(PILLAR_GROUND_FILL_LIMIT) {
                            editor.set_block_absolute(GRAY_CONCRETE, bx, y, bz, None, Some(&[]));
                        }
                        editor.register_support_column(bx, bz, GRAY_CONCRETE);
                        continue;
                    }
                    let bottom = deck_y + dy;
                    if bottom > ground {
                        for y in (ground..bottom).rev().take(PILLAR_GROUND_FILL_LIMIT) {
                            editor.set_block_with_properties_absolute(
                                rotated_block(block, k),
                                bx,
                                y,
                                bz,
                                None,
                                Some(&[]),
                            );
                        }
                    }
                    // Lets the water carve extend the foot to the bed.
                    editor.register_support_column(bx, bz, block.block);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clip_column_cuts_the_middle_and_keeps_the_parapet() {
        // A deck reaching 19 columns out, cut to 8 on its side.
        assert_eq!(clip_column(0, 8, 19), Some(0));
        assert_eq!(clip_column(5, 8, 19), Some(5));
        assert_eq!(clip_column(6, 8, 19), None);
        assert_eq!(clip_column(16, 8, 19), None);
        assert_eq!(clip_column(17, 8, 19), Some(6));
        assert_eq!(clip_column(19, 8, 19), Some(8));
        assert_eq!(clip_column(-19, 8, 19), Some(-8));
        // Uncut sides are untouched.
        assert_eq!(clip_column(17, 19, 19), Some(17));
        assert_eq!(clip_column(-18, 18, 18), Some(-18));
    }

    #[test]
    fn all_bridge_segments_parse() {
        let mods = modules();
        assert_eq!(mods.len(), 4);
        for m in mods {
            assert!(m.length >= 19);
            assert!(m.slices.iter().all(|s| !s.is_empty()));
        }
        assert!(mods[0].has_pillars && mods[1].has_pillars);
        assert!(!mods[2].has_pillars && !mods[3].has_pillars);
        assert!(!mods[0].feet.iter().all(|f| f.is_empty()));
    }
}
