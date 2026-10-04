//! Footprint-based height matching, in Minecraft XZ.
//!
//! The older lookup asked "which provider point is nearest to the polygon's
//! centroid (within ~30 m)?". That picks up a neighbour's point (a bus shelter
//! next to a mall's tip) and misses big buildings whose centroid is far from every
//! point. This module instead asks "which provider points lie *inside* the
//! polygon?", and completes the polygons that have no such evidence from a
//! touching sibling of the same OSM building (GSI cuts one building into several
//! polygons along vector-tile edges).
//!
//! Everything here is pure geometry over [`McSample`]s; the providers and the
//! lat/lng transform stay in [`super::HeightResolver`].

/// A provider height sample placed in (fractional) Minecraft XZ.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct McSample {
    pub x: f64,
    pub z: f64,
    pub height_m: f64,
}

/// How far (blocks) outside a polygon's outline a sample that lies inside no
/// footprint at all may still be adopted: the centroid of a small building can
/// sit a little outside a roughly traced polygon.
pub const EDGE_TOLERANCE: f64 = 4.0;

/// Two polygons count as touching where this many blocks of the smaller polygon's
/// outline lie within [`TOUCH_TOLERANCE`] of the larger one.
const MIN_SHARED_OUTLINE: usize = 6;
/// Without a common OSM outline, a GSI piece must also share this part of its
/// outline with the larger piece ...
const MIN_SHARED_SHARE_NO_OUTLINE: f64 = 0.25;
/// ... and the larger piece must be at least this many times its area. With a
/// common OSM outline the ratio only has to say "larger".
const MIN_AREA_RATIO_NO_OUTLINE: f64 = 4.0;
const MIN_AREA_RATIO_WITH_OUTLINE: f64 = 1.5;
/// A piece with its own Inside height is overridden by the larger sibling only
/// when its height is below this fraction of the sibling's.
const OVERRIDE_BELOW_FRACTION: f64 = 0.5;
const TOUCH_TOLERANCE: f64 = 3.0;
/// Share of a weak polygon that must lie inside the OSM building outline.
const MIN_COVER_IN_OUTLINE: f64 = 0.8;
/// Share of the donor polygon that must lie inside the same OSM outline.
const MIN_DONOR_IN_OUTLINE: f64 = 0.5;
/// A weak polygon mostly inside the donor is a rooftop/annex detail, not a split piece.
const MAX_WEAK_INSIDE_DONOR: f64 = 0.75;
/// An OSM outline without evidence of its own takes the height of the GSI
/// fragment that covers at least this share of it (OSM and GSI draw the same
/// building twice; the two copies must not disagree).
const MIN_OUTLINE_COVERED_BY_FRAGMENT: f64 = 0.5;
/// Cap on the sample grid used to estimate overlap shares.
const COVER_GRID_CELLS: f64 = 400.0;

/// One building polygon (closed or open ring of block coordinates).
#[derive(Debug, Clone)]
pub struct Footprint {
    pub ring: Vec<(i32, i32)>,
    /// A GSI vector-tile fragment (may be one piece of a larger building).
    /// Only non-fragment (OSM) polygons serve as the "same building" outline.
    pub is_fragment: bool,
}

/// How a footprint's height was established.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HeightBasis {
    /// A provider point lies inside the polygon (strong evidence).
    Inside,
    /// Only a provider point just outside the outline, belonging to no other polygon.
    Edge,
    /// Taken from a touching sibling polygon of the same OSM building.
    Inherited,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AssignedHeight {
    pub height_m: f64,
    pub basis: HeightBasis,
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

type Bounds = (i32, i32, i32, i32); // min_x, max_x, min_z, max_z

pub fn ring_bounds(ring: &[(i32, i32)]) -> Option<Bounds> {
    let first = ring.first()?;
    let mut b = (first.0, first.0, first.1, first.1);
    for &(x, z) in ring {
        b.0 = b.0.min(x);
        b.1 = b.1.max(x);
        b.2 = b.2.min(z);
        b.3 = b.3.max(z);
    }
    Some(b)
}

fn bounds_overlap(a: Bounds, b: Bounds, margin: i32) -> bool {
    a.0 - margin <= b.1 && b.0 - margin <= a.1 && a.2 - margin <= b.3 && b.2 - margin <= a.3
}

/// Even-odd point-in-polygon; the ring need not repeat its first point.
pub fn point_in_ring(x: f64, z: f64, ring: &[(i32, i32)]) -> bool {
    let n = ring.len();
    if n < 3 {
        return false;
    }
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (xi, zi) = (ring[i].0 as f64, ring[i].1 as f64);
        let (xj, zj) = (ring[j].0 as f64, ring[j].1 as f64);
        if (zi > z) != (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi {
            inside = !inside;
        }
        j = i;
    }
    inside
}

fn dist_to_segment(px: f64, pz: f64, a: (i32, i32), b: (i32, i32)) -> f64 {
    let (ax, az, bx, bz) = (a.0 as f64, a.1 as f64, b.0 as f64, b.1 as f64);
    let (dx, dz) = (bx - ax, bz - az);
    let len_sq = dx * dx + dz * dz;
    let t = if len_sq <= f64::EPSILON {
        0.0
    } else {
        (((px - ax) * dx + (pz - az) * dz) / len_sq).clamp(0.0, 1.0)
    };
    ((px - (ax + t * dx)).powi(2) + (pz - (az + t * dz)).powi(2)).sqrt()
}

/// Distance from a point to the polygon outline.
pub fn dist_to_ring(x: f64, z: f64, ring: &[(i32, i32)]) -> f64 {
    let n = ring.len();
    if n == 0 {
        return f64::INFINITY;
    }
    if n == 1 {
        return ((x - ring[0].0 as f64).powi(2) + (z - ring[0].1 as f64).powi(2)).sqrt();
    }
    let mut best = f64::INFINITY;
    let mut j = n - 1;
    for i in 0..n {
        best = best.min(dist_to_segment(x, z, ring[j], ring[i]));
        j = i;
    }
    best
}

/// 0 when the point is inside the polygon, otherwise the distance to its outline.
fn dist_to_polygon(x: f64, z: f64, ring: &[(i32, i32)]) -> f64 {
    if point_in_ring(x, z, ring) {
        0.0
    } else {
        dist_to_ring(x, z, ring)
    }
}

/// Points along the outline, about one per block.
fn outline_points(ring: &[(i32, i32)]) -> Vec<(f64, f64)> {
    let n = ring.len();
    let mut pts = Vec::new();
    if n < 2 {
        return pts;
    }
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (ring[j], ring[i]);
        let len = (((b.0 - a.0) as f64).powi(2) + ((b.1 - a.1) as f64).powi(2)).sqrt();
        let steps = len.ceil().max(1.0) as usize;
        for s in 0..steps {
            let t = s as f64 / steps as f64;
            pts.push((
                a.0 as f64 + (b.0 - a.0) as f64 * t,
                a.1 as f64 + (b.1 - a.1) as f64 * t,
            ));
        }
        j = i;
    }
    pts
}

/// Share of `inner` (by area, estimated on a grid) that lies inside `outer`.
fn share_inside(inner: &[(i32, i32)], outer: &[(i32, i32)]) -> f64 {
    let Some(b) = ring_bounds(inner) else {
        return 0.0;
    };
    let w = (b.1 - b.0 + 1) as f64;
    let h = (b.3 - b.2 + 1) as f64;
    let step = ((w * h / COVER_GRID_CELLS).sqrt().ceil() as i32).max(1);
    let (mut total, mut hit) = (0usize, 0usize);
    let mut z = b.2;
    while z <= b.3 {
        let mut x = b.0;
        while x <= b.1 {
            let (cx, cz) = (x as f64 + 0.5, z as f64 + 0.5);
            if point_in_ring(cx, cz, inner) {
                total += 1;
                if point_in_ring(cx, cz, outer) {
                    hit += 1;
                }
            }
            x += step;
        }
        z += step;
    }
    if total == 0 {
        0.0
    } else {
        hit as f64 / total as f64
    }
}

// ---------------------------------------------------------------------------
// Assignment
// ---------------------------------------------------------------------------

/// Height for every footprint from provider samples.
///
/// `samples` holds one list per provider in priority order (as returned by
/// `HeightResolver::samples_in_mc_rect`). Steps:
///
/// 1. Inside: the tallest sample inside the polygon (first provider that has one).
/// 2. Edge: otherwise the nearest sample within [`EDGE_TOLERANCE`] of the outline
///    that lies inside *no* footprint (it belongs to a building we know about, or
///    to nothing we draw).
/// 3. Split completion (one building cut into several polygons has one height):
///    a polygon takes the height of the largest touching *Inside* polygon.
///    - Same OSM outline (both mostly inside one OSM building polygon): a polygon
///      without Inside height always takes it; one with its own Inside height only
///      if that is below half the larger piece's.
///    - No common OSM outline (GSI pieces only, none of them in a different OSM
///      building): only a polygon without Inside height takes it, and only when
///      the donor is >= 4x larger and a quarter of its outline touches the donor.
///
///    Donors are Inside polygons as of step 2, so nothing chains.
/// 4. Duplicate OSM outline: an OSM polygon still without an Inside height takes the
///    height of the Inside GSI fragment that covers most of it, so the OSM and GSI
///    copies of one building agree.
pub fn assign_heights(
    footprints: &[Footprint],
    samples: &[Vec<McSample>],
) -> Vec<Option<AssignedHeight>> {
    let bounds: Vec<Option<Bounds>> = footprints.iter().map(|f| ring_bounds(&f.ring)).collect();
    // contained[p][i]: sample i of provider p lies inside some footprint.
    let mut contained: Vec<Vec<bool>> = samples.iter().map(|s| vec![false; s.len()]).collect();
    // inside[f][p]: samples of provider p inside footprint f.
    let mut inside: Vec<Vec<Vec<usize>>> = Vec::with_capacity(footprints.len());

    for (fi, fp) in footprints.iter().enumerate() {
        let mut per_provider = Vec::with_capacity(samples.len());
        for (p, list) in samples.iter().enumerate() {
            let mut hits = Vec::new();
            if let Some(b) = bounds[fi] {
                for (i, s) in list.iter().enumerate() {
                    if s.x >= b.0 as f64
                        && s.x <= (b.1 + 1) as f64
                        && s.z >= b.2 as f64
                        && s.z <= (b.3 + 1) as f64
                        && point_in_ring(s.x, s.z, &fp.ring)
                    {
                        hits.push(i);
                        contained[p][i] = true;
                    }
                }
            }
            per_provider.push(hits);
        }
        inside.push(per_provider);
    }

    let mut result: Vec<Option<AssignedHeight>> = vec![None; footprints.len()];

    // 1. Inside
    for fi in 0..footprints.len() {
        for (p, hits) in inside[fi].iter().enumerate() {
            if let Some(h) = hits
                .iter()
                .map(|&i| samples[p][i].height_m)
                .fold(None, |acc: Option<f64>, h| {
                    Some(acc.map_or(h, |a| a.max(h)))
                })
            {
                result[fi] = Some(AssignedHeight {
                    height_m: h,
                    basis: HeightBasis::Inside,
                });
                break;
            }
        }
    }

    // 2. Edge
    for (fi, fp) in footprints.iter().enumerate() {
        if result[fi].is_some() {
            continue;
        }
        let Some(b) = bounds[fi] else { continue };
        let margin = EDGE_TOLERANCE.ceil();
        for (p, list) in samples.iter().enumerate() {
            let mut best: Option<(f64, f64)> = None; // (distance, height)
            for (i, s) in list.iter().enumerate() {
                if contained[p][i]
                    || s.x < b.0 as f64 - margin
                    || s.x > (b.1 + 1) as f64 + margin
                    || s.z < b.2 as f64 - margin
                    || s.z > (b.3 + 1) as f64 + margin
                {
                    continue;
                }
                let d = dist_to_ring(s.x, s.z, &fp.ring);
                if d <= EDGE_TOLERANCE && best.is_none_or(|(bd, _)| d < bd) {
                    best = Some((d, s.height_m));
                }
            }
            if let Some((_, h)) = best {
                result[fi] = Some(AssignedHeight {
                    height_m: h,
                    basis: HeightBasis::Edge,
                });
                break;
            }
        }
    }

    // 3. Split completion (donors are the Inside results as they stand now).
    let strong: Vec<bool> = result
        .iter()
        .map(|r| r.is_some_and(|a| a.basis == HeightBasis::Inside))
        .collect();
    let areas: Vec<f64> = footprints.iter().map(|f| ring_area(&f.ring)).collect();
    let mut inherited: Vec<(usize, f64)> = Vec::new();
    // arnis-jp: 「体感リアルサイズ」の分割建物の項目がオフなら行わない。
    let split_count = if crate::perceived_size::fill_split_buildings() {
        footprints.len()
    } else {
        0
    };
    for wi in 0..split_count {
        let own = result[wi].filter(|_| strong[wi]).map(|a| a.height_m);
        if let Some(h) =
            inherit_from_larger_sibling(wi, own, footprints, &bounds, &areas, &strong, &result)
        {
            inherited.push((wi, h));
        }
    }
    for (wi, h) in inherited {
        result[wi] = Some(AssignedHeight {
            height_m: h,
            basis: HeightBasis::Inherited,
        });
    }

    // 4. Duplicate OSM outline (donors: GSI fragments with Inside evidence).
    let mut covered: Vec<(usize, f64)> = Vec::new();
    for ci in 0..footprints.len() {
        if strong[ci] || footprints[ci].is_fragment {
            continue;
        }
        let Some(cb) = bounds[ci] else { continue };
        let mut best: Option<(f64, f64)> = None; // (share of the outline covered, height)
        for fi in 0..footprints.len() {
            if !strong[fi] || !footprints[fi].is_fragment {
                continue;
            }
            if !bounds[fi].is_some_and(|fb| bounds_overlap(cb, fb, 0)) {
                continue;
            }
            let share = share_inside(&footprints[ci].ring, &footprints[fi].ring);
            if share >= MIN_OUTLINE_COVERED_BY_FRAGMENT && best.is_none_or(|(bs, _)| share > bs) {
                best = result[fi].map(|a| (share, a.height_m));
            }
        }
        if let Some((_, h)) = best {
            covered.push((ci, h));
        }
    }
    for (ci, h) in covered {
        result[ci] = Some(AssignedHeight {
            height_m: h,
            basis: HeightBasis::Inherited,
        });
    }
    result
}

/// Polygon area (shoelace), in blocks squared.
fn ring_area(ring: &[(i32, i32)]) -> f64 {
    let n = ring.len();
    if n < 3 {
        return 0.0;
    }
    let mut sum = 0.0;
    let mut j = n - 1;
    for i in 0..n {
        sum += ring[j].0 as f64 * ring[i].1 as f64 - ring[i].0 as f64 * ring[j].1 as f64;
        j = i;
    }
    sum.abs() / 2.0
}

/// Height polygon `wi` takes over from the largest touching Inside polygon that
/// is plausibly the same building (see [`assign_heights`], step 3). `own` is its
/// own Inside height, if it has one.
fn inherit_from_larger_sibling(
    wi: usize,
    own: Option<f64>,
    footprints: &[Footprint],
    bounds: &[Option<Bounds>],
    areas: &[f64],
    strong: &[bool],
    result: &[Option<AssignedHeight>],
) -> Option<f64> {
    let small = &footprints[wi];
    let wb = bounds[wi]?;

    // OSM outlines that contain (nearly) all of the polygon.
    let outlines: Vec<usize> = (0..footprints.len())
        .filter(|&ci| {
            ci != wi
                && !footprints[ci].is_fragment
                && bounds[ci].is_some_and(|cb| bounds_overlap(wb, cb, 0))
                && share_inside(&small.ring, &footprints[ci].ring) >= MIN_COVER_IN_OUTLINE
        })
        .collect();
    // Is the polygon mostly inside some OSM building that does not contain the donor?
    let in_other_osm_building = |si: usize| -> bool {
        (0..footprints.len()).any(|ci| {
            ci != wi
                && ci != si
                && !footprints[ci].is_fragment
                && bounds[ci].is_some_and(|cb| bounds_overlap(wb, cb, 0))
                && !outlines.contains(&ci)
                && share_inside(&small.ring, &footprints[ci].ring) >= MIN_COVER_IN_OUTLINE
        })
    };

    let outline = outline_points(&small.ring);
    // (area, shared outline blocks, height)
    let mut best: Option<(f64, usize, f64)> = None;
    for si in 0..footprints.len() {
        if si == wi || !strong[si] || outlines.contains(&si) || areas[si] <= areas[wi] {
            continue;
        }
        let Some(sb) = bounds[si] else { continue };
        if !bounds_overlap(wb, sb, TOUCH_TOLERANCE.ceil() as i32) {
            continue;
        }
        let donor = &footprints[si];
        // The polygon must protrude from the donor, not sit on its roof.
        if share_inside(&small.ring, &donor.ring) > MAX_WEAK_INSIDE_DONOR {
            continue;
        }
        let shared = outline
            .iter()
            .filter(|&&(x, z)| dist_to_polygon(x, z, &donor.ring) <= TOUCH_TOLERANCE)
            .count();
        if shared < MIN_SHARED_OUTLINE {
            continue;
        }
        let ratio = areas[si] / areas[wi].max(1.0);
        let in_same_outline = outlines
            .iter()
            .any(|&ci| share_inside(&donor.ring, &footprints[ci].ring) >= MIN_DONOR_IN_OUTLINE);
        let eligible = if in_same_outline {
            ratio >= MIN_AREA_RATIO_WITH_OUTLINE
        } else {
            // Geometry alone: GSI pieces only, never across an OSM building boundary,
            // never over a polygon that has its own evidence.
            own.is_none()
                && small.is_fragment
                && donor.is_fragment
                && ratio >= MIN_AREA_RATIO_NO_OUTLINE
                && shared as f64 >= MIN_SHARED_SHARE_NO_OUTLINE * outline.len() as f64
                && !in_other_osm_building(si)
        };
        if !eligible {
            continue;
        }
        let h = result[si]?.height_m;
        if best.is_none_or(|(ba, bs, _)| areas[si] > ba || (areas[si] == ba && shared > bs)) {
            best = Some((areas[si], shared, h));
        }
    }
    let (_, _, donor_h) = best?;
    match own {
        None => Some(donor_h),
        // Own Inside evidence: kept unless it is far below the larger piece's.
        Some(h) if h < OVERRIDE_BELOW_FRACTION * donor_h => Some(donor_h),
        Some(_) => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x0: i32, z0: i32, x1: i32, z1: i32) -> Vec<(i32, i32)> {
        vec![(x0, z0), (x1, z0), (x1, z1), (x0, z1), (x0, z0)]
    }

    fn fp(ring: Vec<(i32, i32)>, is_fragment: bool) -> Footprint {
        Footprint { ring, is_fragment }
    }

    fn sample(x: f64, z: f64, h: f64) -> McSample {
        McSample { x, z, height_m: h }
    }

    #[test]
    fn point_in_ring_and_distance() {
        let r = rect(0, 0, 10, 10);
        assert!(point_in_ring(5.0, 5.0, &r));
        assert!(!point_in_ring(11.0, 5.0, &r));
        assert!((dist_to_ring(13.0, 5.0, &r) - 3.0).abs() < 1e-9);
    }

    #[test]
    fn inside_sample_wins_and_tallest_is_taken() {
        let fps = vec![fp(rect(0, 0, 40, 40), false)];
        let samples = vec![vec![sample(10.0, 10.0, 9.0), sample(30.0, 30.0, 27.0)]];
        let r = assign_heights(&fps, &samples);
        assert_eq!(
            r[0],
            Some(AssignedHeight {
                height_m: 27.0,
                basis: HeightBasis::Inside
            })
        );
    }

    #[test]
    fn neighbour_small_building_point_is_not_picked_up() {
        // A big polygon with no sample inside; a bus shelter (own footprint) sits
        // right beside it. The old centroid-nearest lookup returned the shelter's 3 m.
        let big = fp(rect(0, 0, 100, 60), true);
        let shelter = fp(rect(104, 20, 110, 26), true);
        let samples = vec![vec![sample(107.0, 23.0, 3.0)]];
        let r = assign_heights(&[big, shelter], &samples);
        assert_eq!(r[0], None);
        assert_eq!(r[1].unwrap().basis, HeightBasis::Inside);
    }

    #[test]
    fn stray_point_outside_all_footprints_is_edge_only() {
        let a = fp(rect(0, 0, 20, 20), true);
        // 2 blocks outside the outline, inside no footprint: weak Edge match.
        let near = vec![vec![sample(22.0, 10.0, 3.0)]];
        let r = assign_heights(std::slice::from_ref(&a), &near);
        assert_eq!(r[0].unwrap().basis, HeightBasis::Edge);
        // 30 blocks away: nothing.
        let far = vec![vec![sample(50.0, 10.0, 3.0)]];
        let r = assign_heights(&[a], &far);
        assert_eq!(r[0], None);
    }

    #[test]
    fn split_piece_inherits_from_touching_sibling_in_same_osm_building() {
        // OSM outline covers body (z 0..100) and tip (z 100..140).
        let outline = fp(rect(0, 0, 80, 140), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let tip = fp(rect(10, 98, 70, 140), true);
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[outline, body, tip], &samples);
        assert_eq!(r[1].unwrap().basis, HeightBasis::Inside);
        assert_eq!(
            r[2],
            Some(AssignedHeight {
                height_m: 29.0,
                basis: HeightBasis::Inherited
            })
        );
    }

    #[test]
    fn weak_edge_match_is_overridden_by_sibling() {
        let outline = fp(rect(0, 0, 80, 140), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let tip = fp(rect(10, 98, 70, 140), true);
        // 3 m shelter point just outside the tip's outline, inside nothing.
        let samples = vec![vec![sample(40.0, 50.0, 29.0), sample(40.0, 142.0, 3.0)]];
        let r = assign_heights(&[outline, body, tip], &samples);
        assert_eq!(r[2].unwrap().height_m, 29.0);
        assert_eq!(r[2].unwrap().basis, HeightBasis::Inherited);
    }

    #[test]
    fn no_inheritance_without_osm_outline_when_areas_are_alike() {
        // 8000 vs 2520 blocks^2: not the "much larger" donor the geometry-only rule needs.
        let body = fp(rect(0, 0, 80, 100), true);
        let tip = fp(rect(10, 98, 70, 140), true);
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[body, tip], &samples);
        assert_eq!(r[1], None);
    }

    #[test]
    fn small_piece_without_data_follows_a_much_larger_touching_piece_even_without_osm() {
        let body = fp(rect(0, 0, 80, 100), true); // 8000
        let small = fp(rect(20, 98, 60, 120), true); // 880, 9x smaller, top edge on the body
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[body, small], &samples);
        assert_eq!(r[1].unwrap().height_m, 29.0);
        assert_eq!(r[1].unwrap().basis, HeightBasis::Inherited);
    }

    #[test]
    fn small_piece_with_its_own_height_is_not_overridden_without_osm_outline() {
        // A low shop leaning on a big store: both measured, no common OSM building.
        let store = fp(rect(0, 0, 80, 100), true);
        let shop = fp(rect(20, 98, 60, 120), true);
        let samples = vec![vec![sample(40.0, 50.0, 29.0), sample(40.0, 110.0, 4.0)]];
        let r = assign_heights(&[store, shop], &samples);
        assert_eq!(r[1].unwrap().height_m, 4.0);
        assert_eq!(r[1].unwrap().basis, HeightBasis::Inside);
    }

    #[test]
    fn piece_in_same_osm_building_with_very_different_own_height_follows_the_larger() {
        let outline = fp(rect(0, 0, 80, 140), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let tip_low = fp(rect(10, 98, 70, 140), true);
        let tip_close = fp(rect(10, 98, 70, 140), true);
        // 8 m is under half of 29 m: follows. 20 m is not: keeps its own value.
        let low = vec![vec![sample(40.0, 50.0, 29.0), sample(40.0, 120.0, 8.0)]];
        let r = assign_heights(&[outline.clone(), body.clone(), tip_low], &low);
        assert_eq!(r[2].unwrap().height_m, 29.0);
        let close = vec![vec![sample(40.0, 50.0, 29.0), sample(40.0, 120.0, 20.0)]];
        let r = assign_heights(&[outline, body, tip_close], &close);
        assert_eq!(r[2].unwrap().height_m, 20.0);
    }

    #[test]
    fn low_neighbour_in_its_own_osm_building_is_not_raised() {
        // A one-storey shop (own OSM outline, measured 4 m) touching a tall store.
        let store_outline = fp(rect(0, 0, 80, 100), false);
        let shop_outline = fp(rect(10, 100, 70, 130), false);
        let store = fp(rect(0, 0, 80, 100), true);
        let shop = fp(rect(10, 98, 70, 130), true);
        let samples = vec![vec![sample(40.0, 50.0, 29.0), sample(40.0, 115.0, 4.0)]];
        let r = assign_heights(&[store_outline, shop_outline, store, shop], &samples);
        assert_eq!(r[3].unwrap().height_m, 4.0);
    }

    #[test]
    fn no_inheritance_when_not_touching() {
        let outline = fp(rect(0, 0, 80, 200), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let far_piece = fp(rect(10, 130, 70, 190), true); // 30 blocks away
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[outline, body, far_piece], &samples);
        assert_eq!(r[2], None);
    }

    #[test]
    fn no_inheritance_across_different_osm_buildings() {
        // Two touching GSI pieces, but each inside its own OSM outline.
        let outline_a = fp(rect(0, 0, 80, 100), false);
        let outline_b = fp(rect(0, 100, 80, 140), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let other = fp(rect(10, 100, 70, 140), true);
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[outline_a, outline_b, body, other], &samples);
        assert_eq!(r[3], None);
    }

    #[test]
    fn inheritance_does_not_chain() {
        // body (strong) - mid (weak, inherits) - end (weak, touches only mid).
        let outline = fp(rect(0, 0, 80, 300), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let mid = fp(rect(10, 98, 70, 160), true);
        let end = fp(rect(20, 160, 60, 220), true);
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[outline, body, mid, end], &samples);
        assert_eq!(r[2].unwrap().basis, HeightBasis::Inherited);
        assert_eq!(r[3], None);
    }

    #[test]
    fn osm_outline_without_data_takes_the_height_of_the_gsi_fragment_that_covers_it() {
        // The mall's OSM polygon has no point inside (the only point sits in a
        // notch of the OSM outline); the GSI body covers most of it and has one.
        let osm = fp(rect(10, 0, 90, 100), false);
        let gsi = fp(rect(0, 0, 100, 100), true);
        let samples = vec![vec![sample(5.0, 50.0, 28.5)]];
        let r = assign_heights(&[osm, gsi], &samples);
        assert_eq!(r[1].unwrap().basis, HeightBasis::Inside);
        assert_eq!(
            r[0],
            Some(AssignedHeight {
                height_m: 28.5,
                basis: HeightBasis::Inherited
            })
        );
    }

    #[test]
    fn osm_outline_keeps_none_when_gsi_fragment_covers_little_of_it() {
        let osm = fp(rect(0, 20, 100, 120), false);
        let gsi = fp(rect(0, 0, 100, 40), true); // covers 20 % of the outline only
        let samples = vec![vec![sample(50.0, 10.0, 28.5)]];
        let r = assign_heights(&[osm, gsi], &samples);
        assert_eq!(r[0], None);
    }

    #[test]
    fn annex_on_the_roof_of_a_sibling_keeps_its_own_height() {
        let outline = fp(rect(0, 0, 80, 100), false);
        let body = fp(rect(0, 0, 80, 100), true);
        let annex = fp(rect(10, 10, 30, 30), true); // wholly inside the body
        let samples = vec![vec![sample(40.0, 50.0, 29.0)]];
        let r = assign_heights(&[outline, body, annex], &samples);
        assert_eq!(r[2], None);
    }
}
