//! Real footprint of a module deck, taken from the `man_made=bridge` outline mapped over it.
//!
//! A module deck is swept along one centerline and is wider than most roads, so beside the
//! structure it hangs over whatever runs at grade (sidewalks, cycle tracks, link roads).
//! Where the bridge is outlined the deck is held to that outline plus the road surface.

use std::collections::HashSet;

/// Cells of margin kept around the outline for kerb and parapet.
const OUTLINE_MARGIN: i32 = 2;
/// Cells of margin kept around every road of the structure so the carriageway stays decked.
const ROAD_MARGIN: i32 = 1;

pub struct DeckClip {
    allowed: HashSet<(i32, i32)>,
}

impl DeckClip {
    /// `roads`: (cell, half-width) of every way of the structure; `outlines`: bridge outline
    /// polygons mapped over it; `reach`: the widest deck half-width that could be swept.
    pub fn build(roads: &[((i32, i32), i32)], outlines: &[&[(i32, i32)]], reach: i32) -> Self {
        let mut allowed: HashSet<(i32, i32)> = HashSet::new();
        for &((x, z), half) in roads {
            let r = half + ROAD_MARGIN;
            for dx in -r..=r {
                for dz in -r..=r {
                    allowed.insert((x + dx, z + dz));
                }
            }
        }
        // Only cells a deck could reach are worth testing against the outlines.
        let mut candidates: HashSet<(i32, i32)> = HashSet::new();
        for &((x, z), _) in roads {
            for dx in -reach..=reach {
                for dz in -reach..=reach {
                    candidates.insert((x + dx, z + dz));
                }
            }
        }
        for &(x, z) in &candidates {
            if allowed.contains(&(x, z)) {
                continue;
            }
            if outlines
                .iter()
                .any(|poly| near_polygon(x, z, poly, OUTLINE_MARGIN))
            {
                allowed.insert((x, z));
            }
        }
        Self { allowed }
    }

    pub fn allows(&self, x: i32, z: i32) -> bool {
        self.allowed.contains(&(x, z))
    }

    /// Blocks the deck may extend from (x, z) along unit `dir` before it leaves the footprint.
    pub fn reach_along(&self, x: i32, z: i32, dir: (f32, f32), max: i32) -> i32 {
        for k in 1..=max {
            let cx = (x as f32 + dir.0 * k as f32).round() as i32;
            let cz = (z as f32 + dir.1 * k as f32).round() as i32;
            if !self.allows(cx, cz) {
                return k - 1;
            }
        }
        max
    }
}

/// True when (x, z) is inside the polygon or within `margin` cells of its boundary.
fn near_polygon(x: i32, z: i32, poly: &[(i32, i32)], margin: i32) -> bool {
    let (mut min_x, mut max_x, mut min_z, mut max_z) = (i32::MAX, i32::MIN, i32::MAX, i32::MIN);
    for &(px, pz) in poly {
        min_x = min_x.min(px);
        max_x = max_x.max(px);
        min_z = min_z.min(pz);
        max_z = max_z.max(pz);
    }
    if x < min_x - margin || x > max_x + margin || z < min_z - margin || z > max_z + margin {
        return false;
    }
    if point_in_polygon(x, z, poly) {
        return true;
    }
    let m2 = (margin * margin) as f64;
    poly.windows(2)
        .any(|seg| dist2_to_segment(x as f64, z as f64, seg[0], seg[1]) <= m2)
}

fn point_in_polygon(x: i32, z: i32, poly: &[(i32, i32)]) -> bool {
    let n = poly.len();
    if n < 3 {
        return false;
    }
    let (xf, zf) = (x as f64, z as f64);
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (xi, zi) = (poly[i].0 as f64, poly[i].1 as f64);
        let (xj, zj) = (poly[j].0 as f64, poly[j].1 as f64);
        if ((zi > zf) != (zj > zf)) && xf < (xj - xi) * (zf - zi) / (zj - zi) + xi {
            inside = !inside;
        }
        j = i;
    }
    inside
}

fn dist2_to_segment(px: f64, pz: f64, a: (i32, i32), b: (i32, i32)) -> f64 {
    let (ax, az, bx, bz) = (a.0 as f64, a.1 as f64, b.0 as f64, b.1 as f64);
    let (dx, dz) = (bx - ax, bz - az);
    let len2 = dx * dx + dz * dz;
    let t = if len2 == 0.0 {
        0.0
    } else {
        (((px - ax) * dx + (pz - az) * dz) / len2).clamp(0.0, 1.0)
    };
    let (cx, cz) = (ax + t * dx, az + t * dz);
    (px - cx).powi(2) + (pz - cz).powi(2)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x0: i32, z0: i32, x1: i32, z1: i32) -> Vec<(i32, i32)> {
        vec![(x0, z0), (x1, z0), (x1, z1), (x0, z1), (x0, z0)]
    }

    #[test]
    fn deck_is_held_to_outline_plus_road_margin() {
        // Road along z=50 (half-width 2); outline z 44..56.
        let roads: Vec<((i32, i32), i32)> = (10..60).map(|x| ((x, 50), 2)).collect();
        let outline = rect(0, 44, 70, 56);
        let clip = DeckClip::build(&roads, &[&outline], 19);
        // Outline plus its margin is decked, nothing further out.
        assert!(clip.allows(30, 58));
        assert!(!clip.allows(30, 59));
        assert!(clip.allows(30, 42));
        assert!(!clip.allows(30, 41));
        assert_eq!(clip.reach_along(30, 50, (0.0, 1.0), 19), 8);
        assert_eq!(clip.reach_along(30, 50, (0.0, -1.0), 19), 8);
    }

    #[test]
    fn road_stays_decked_when_the_outline_is_narrower() {
        let roads: Vec<((i32, i32), i32)> = (10..60).map(|x| ((x, 50), 5)).collect();
        let outline = rect(0, 48, 70, 52);
        let clip = DeckClip::build(&roads, &[&outline], 19);
        assert_eq!(clip.reach_along(30, 50, (0.0, 1.0), 19), 6);
    }
}
