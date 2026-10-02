/// Japan-specific export context for metadata / mapping JSON output.
///
/// Bundles `BuildingMetadataCollector` and `WorldMappingCollector`
/// together with the coordinate transform parameters that only
/// exist for `world_mapping.json`.  Keeping these separate from
/// the upstream `GenerationOptions` avoids merge conflicts when
/// upstream adds or changes fields.
use crate::building_height::footprint::{self, AssignedHeight, Footprint, HeightBasis};
use crate::building_height::HeightResolver;
use crate::building_metadata::BuildingMetadataCollector;
use crate::coordinate_system::geographic::LLBBox;
use crate::coordinate_system::transformation::CoordTransformer;
use crate::osm_parser::{ProcessedElement, ProcessedWay};
use crate::world_mapping::WorldMappingCollector;
use std::collections::HashMap;
use std::path::Path;
use std::sync::OnceLock;

/// Coordinate transform parameters needed solely for `world_mapping.json`.
///
/// These are arnis-jp additions that do not exist in upstream.
#[derive(Clone)]
pub struct JpExportOptions {
    pub scale_factor_x: f64,
    pub scale_factor_z: f64,
    pub min_lat: f64,
    pub min_lng: f64,
    pub len_lat: f64,
    pub len_lng: f64,
}

impl JpExportOptions {
    /// Build from an already-constructed `CoordTransformer`.
    pub fn from_transformer(ct: &CoordTransformer) -> Self {
        Self {
            scale_factor_x: ct.scale_factor_x(),
            scale_factor_z: ct.scale_factor_z(),
            min_lat: ct.min_lat(),
            min_lng: ct.min_lng(),
            len_lat: ct.len_lat(),
            len_lng: ct.len_lng(),
        }
    }
}

/// Thread-safe bundle of JP-specific collectors for the generation pipeline.
pub struct JpExportContext {
    pub metadata_collector: BuildingMetadataCollector,
    pub mapping_collector: WorldMappingCollector,
}

impl JpExportContext {
    pub fn new() -> Self {
        Self {
            metadata_collector: BuildingMetadataCollector::new(),
            mapping_collector: WorldMappingCollector::new(),
        }
    }

    /// Save all JP-specific export artefacts (buildings.json, world_mapping.json).
    pub fn save(
        &self,
        output_path: &Path,
        llbbox: &LLBBox,
        scale: f64,
        jp_opts: &JpExportOptions,
        ground_level: i32,
    ) {
        if let Err(e) = self.metadata_collector.save_to_json(output_path) {
            eprintln!("Warning: Failed to save building metadata: {e}");
        }

        if let Err(e) = self.mapping_collector.save_to_json(
            output_path,
            [
                llbbox.min().lat(),
                llbbox.min().lng(),
                llbbox.max().lat(),
                llbbox.max().lng(),
            ],
            scale,
            jp_opts.scale_factor_x,
            jp_opts.scale_factor_z,
            ground_level,
            jp_opts.min_lat,
            jp_opts.min_lng,
            jp_opts.len_lat,
            jp_opts.len_lng,
        ) {
            eprintln!("Warning: Failed to save world mapping: {e}");
        }
    }
}

/// Everything arnis-jp adds to one world-generation run, bundled so that
/// `GenerationOptions` (and the building pipeline) need only one extra field.
///
/// Shared read-only across tile threads: the collectors are internally
/// synchronised and the resolver is only queried.
pub struct JpGeneration {
    pub export: JpExportContext,
    pub export_opts: JpExportOptions,
    pub height_resolver: HeightResolver,
    /// External heights per building polygon, filled once by
    /// [`prepare_building_heights`](Self::prepare_building_heights) before the tile
    /// threads start. Empty/unset: every building is matched on its own.
    pub building_heights: OnceLock<HashMap<WayKey, Option<AssignedHeight>>>,
}

/// Identity of one building polygon. A way id alone can collide with a relation
/// id (relation outlines are generated under synthetic ways), so the first node
/// and the node count are part of it.
pub type WayKey = (u64, i32, i32, usize);

fn way_key(way: &ProcessedWay) -> Option<WayKey> {
    let first = way.nodes.first()?;
    Some((way.id, first.x, first.z, way.nodes.len()))
}

fn way_ring(way: &ProcessedWay) -> Vec<(i32, i32)> {
    way.nodes.iter().map(|n| (n.x, n.z)).collect()
}

/// A way that is a whole-building outline whose height an external provider may set.
fn is_external_height_candidate(way: &ProcessedWay) -> bool {
    way.nodes.len() >= 3
        && way
            .tags
            .get("building")
            .is_some_and(|v| !v.eq_ignore_ascii_case("no"))
        && !way.tags.contains_key("building:part")
}

impl JpGeneration {
    /// Height resolver, if any external provider (GSI-3D / PLATEAU) is registered.
    pub fn active_height_resolver(&self) -> Option<&HeightResolver> {
        self.height_resolver
            .has_providers()
            .then_some(&self.height_resolver)
    }

    /// Match every building polygon of the run against the external height points
    /// at once, so that a polygon is judged by the points *inside* it and a polygon
    /// without evidence can borrow from a touching piece of the same building
    /// (see [`footprint`]). Call once, before generation starts.
    pub fn prepare_building_heights(&self, elements: &[ProcessedElement]) {
        let Some(resolver) = self.active_height_resolver() else {
            return;
        };
        let ways: Vec<&ProcessedWay> = elements
            .iter()
            .filter_map(|e| match e {
                ProcessedElement::Way(w) if is_external_height_candidate(w) => Some(w),
                _ => None,
            })
            .collect();
        let footprints: Vec<Footprint> = ways
            .iter()
            .map(|w| Footprint {
                ring: way_ring(w),
                is_fragment: crate::gsi_data::is_gsi_way_id(w.id),
            })
            .collect();
        let samples = match samples_around(resolver, &footprints) {
            Some(s) => s,
            None => return,
        };
        let assigned = footprint::assign_heights(&footprints, &samples);

        let mut map = HashMap::new();
        let (mut inside, mut edge, mut inherited) = (0, 0, 0);
        for (way, a) in ways.iter().zip(assigned) {
            let Some(key) = way_key(way) else { continue };
            match a.map(|a| a.basis) {
                Some(HeightBasis::Inside) => inside += 1,
                Some(HeightBasis::Edge) => edge += 1,
                Some(HeightBasis::Inherited) => inherited += 1,
                None => {}
            }
            map.insert(key, a);
        }
        println!(
            "[JP] External building heights: {} polygons ({} inside, {} edge, {} inherited from a touching piece), {} without data",
            inside + edge + inherited,
            inside,
            edge,
            inherited,
            ways.len().saturating_sub(inside + edge + inherited)
        );
        let _ = self.building_heights.set(map);
    }

    /// Wall height in blocks (and the tall-building flag) from an external provider
    /// (GSI-3D / PLATEAU), judged by the points inside the footprint.
    ///
    /// None when no provider is registered, no provider has evidence for the building,
    /// or the element is a `building:part` (parts carry their own heights in OSM).
    pub fn external_building_height(&self, way: &ProcessedWay, scale: f64) -> Option<(i32, bool)> {
        let resolver = self.active_height_resolver()?;
        if !is_external_height_candidate(way) {
            return None;
        }
        let prepared = self
            .building_heights
            .get()
            .zip(way_key(way))
            .and_then(|(map, key)| map.get(&key).copied());
        let assigned = match prepared {
            // Prepared polygon: its result (including "no data") is final.
            Some(result) => result,
            // Not part of the prepared set (relation outline, or no pre-pass): match alone.
            None => {
                let fps = [Footprint {
                    ring: way_ring(way),
                    is_fragment: crate::gsi_data::is_gsi_way_id(way.id),
                }];
                let samples = samples_around(resolver, &fps)?;
                footprint::assign_heights(&fps, &samples)
                    .into_iter()
                    .next()
                    .flatten()
            }
        }?;
        let height_m = assigned.height_m;
        let blocks = ((height_m * scale).round() as i32).max(3);
        Some((blocks, height_m > 28.0))
    }

    /// Record one generated building for buildings.json.
    #[allow(clippy::too_many_arguments)]
    pub fn record_building(
        &self,
        way: &ProcessedWay,
        building_type: &str,
        bounds: (i32, i32, i32, i32),
        height: i32,
        base_y: i32,
        floor_area: &[(i32, i32)],
    ) {
        self.export
            .metadata_collector
            .add(crate::building_metadata::BuildingMetadata {
                osm_id: way.id,
                name: way.tags.get("name").cloned(),
                building_type: building_type.to_string(),
                tags: way.tags.clone(),
                min_x: bounds.0,
                max_x: bounds.1,
                min_z: bounds.2,
                max_z: bounds.3,
                height,
                base_y,
                floor_area: floor_area.iter().map(|&(x, z)| [x, z]).collect(),
            });
    }

    /// Save buildings.json / world_mapping.json into the world folder.
    pub fn save(&self, output_path: &Path, llbbox: &LLBBox, scale: f64, ground_level: i32) {
        self.export
            .save(output_path, llbbox, scale, &self.export_opts, ground_level);
    }
}

/// Provider samples in the area covered by the footprints plus the edge reach.
fn samples_around(
    resolver: &HeightResolver,
    footprints: &[Footprint],
) -> Option<Vec<Vec<footprint::McSample>>> {
    let mut all: Option<(i32, i32, i32, i32)> = None;
    for fp in footprints {
        if let Some(b) = footprint::ring_bounds(&fp.ring) {
            all = Some(match all {
                None => b,
                Some(a) => (a.0.min(b.0), a.1.max(b.1), a.2.min(b.2), a.3.max(b.3)),
            });
        }
    }
    let b = all?;
    let m = footprint::EDGE_TOLERANCE + 2.0;
    Some(resolver.samples_in_mc_rect(
        b.0 as f64 - m,
        b.1 as f64 + 1.0 + m,
        b.2 as f64 - m,
        b.3 as f64 + 1.0 + m,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::building_height::{HeightPoint, HeightProvider, HeightResult};
    use crate::osm_parser::ProcessedNode;
    use std::collections::HashMap;

    /// Provider with fixed points, placed through the resolver's own transform
    /// (min_lat 34, min_lng 135, 0.01 deg over 1000 blocks: 1 block = 1e-5 deg).
    struct Points(Vec<(f64, f64, f64)>); // (x, z, height) in blocks

    fn latlng(x: f64, z: f64) -> (f64, f64) {
        (34.0 + (1.0 - z / 1000.0) * 0.01, 135.0 + x / 1000.0 * 0.01)
    }

    impl HeightProvider for Points {
        fn lookup(&self, _lat: f64, _lng: f64) -> Option<HeightResult> {
            None
        }
        fn points_in_bbox(&self, a: f64, b: f64, c: f64, d: f64) -> Vec<HeightPoint> {
            self.0
                .iter()
                .map(|&(x, z, h)| {
                    let (lat, lng) = latlng(x, z);
                    HeightPoint {
                        lat,
                        lng,
                        height_m: h,
                        ground_elv_m: None,
                        source: "test",
                    }
                })
                .filter(|p| p.lat >= a && p.lng >= b && p.lat <= c && p.lng <= d)
                .collect()
        }
        fn name(&self) -> &'static str {
            "test"
        }
    }

    fn generation(points: Vec<(f64, f64, f64)>) -> JpGeneration {
        let mut resolver = HeightResolver::new(34.0, 135.0, 0.01, 0.01, 1000.0, 1000.0);
        resolver.add_provider(Box::new(Points(points)));
        JpGeneration {
            export: JpExportContext::new(),
            export_opts: JpExportOptions {
                scale_factor_x: 1000.0,
                scale_factor_z: 1000.0,
                min_lat: 34.0,
                min_lng: 135.0,
                len_lat: 0.01,
                len_lng: 0.01,
            },
            height_resolver: resolver,
            building_heights: OnceLock::new(),
        }
    }

    fn way(id: u64, x0: i32, z0: i32, x1: i32, z1: i32) -> ProcessedWay {
        let node = |i: usize, x, z| ProcessedNode {
            id: id * 10 + i as u64,
            tags: HashMap::new(),
            x,
            z,
        };
        ProcessedWay {
            id,
            nodes: vec![
                node(0, x0, z0),
                node(1, x1, z0),
                node(2, x1, z1),
                node(3, x0, z1),
                node(0, x0, z0),
            ],
            tags: HashMap::from([("building".to_string(), "yes".to_string())]),
        }
    }

    #[test]
    fn height_comes_from_the_point_inside_not_from_the_nearest_one() {
        // A wide building with its only point (20 m) far from its vertex average,
        // and a low shelter point (3 m) closer to that average, outside the polygon.
        let big = way(1, 0, 0, 100, 40);
        let jp = generation(vec![(95.0, 5.0, 20.0), (50.0, 48.0, 3.0)]);
        let els = vec![ProcessedElement::Way(big.clone())];
        jp.prepare_building_heights(&els);
        assert_eq!(jp.external_building_height(&big, 1.0), Some((20, false)));
    }

    #[test]
    fn tip_piece_takes_the_height_of_its_larger_sibling_in_the_same_osm_building() {
        let osm = way(500, 0, 0, 100, 140);
        let body = way(5_000_000_001, 0, 0, 100, 100);
        let tip = way(5_000_000_002, 10, 98, 90, 140);
        // One point in the body; a shelter point 20 blocks beyond the tip's outline.
        let jp = generation(vec![(50.0, 50.0, 28.5), (50.0, 165.0, 2.6)]);
        let els = vec![
            ProcessedElement::Way(osm.clone()),
            ProcessedElement::Way(body.clone()),
            ProcessedElement::Way(tip.clone()),
        ];
        jp.prepare_building_heights(&els);
        assert_eq!(jp.external_building_height(&body, 1.0), Some((29, true)));
        assert_eq!(jp.external_building_height(&tip, 1.0), Some((29, true)));
        // The point also lies inside the OSM outline: it needs no help.
        assert_eq!(jp.external_building_height(&osm, 1.0), Some((29, true)));
    }

    #[test]
    fn building_without_any_point_has_no_external_height() {
        let lone = way(7, 0, 0, 30, 30);
        let jp = generation(vec![(500.0, 500.0, 12.0)]);
        jp.prepare_building_heights(&[ProcessedElement::Way(lone.clone())]);
        assert_eq!(jp.external_building_height(&lone, 1.0), None);
    }

    #[test]
    fn unprepared_way_is_matched_on_its_own() {
        let w = way(9, 0, 0, 30, 30);
        let jp = generation(vec![(10.0, 10.0, 15.0)]);
        // No pre-pass (e.g. a relation outline): same inside-point rule.
        assert_eq!(jp.external_building_height(&w, 1.0), Some((15, false)));
    }
}
