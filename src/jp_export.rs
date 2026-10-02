/// Japan-specific export context for metadata / mapping JSON output.
///
/// Bundles `BuildingMetadataCollector` and `WorldMappingCollector`
/// together with the coordinate transform parameters that only
/// exist for `world_mapping.json`.  Keeping these separate from
/// the upstream `GenerationOptions` avoids merge conflicts when
/// upstream adds or changes fields.

use crate::building_height::HeightResolver;
use crate::building_metadata::BuildingMetadataCollector;
use crate::coordinate_system::geographic::LLBBox;
use crate::coordinate_system::transformation::CoordTransformer;
use crate::osm_parser::ProcessedWay;
use crate::world_mapping::WorldMappingCollector;
use std::path::Path;

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
}

impl JpGeneration {
    /// Height resolver, if any external provider (GSI-3D / PLATEAU) is registered.
    pub fn active_height_resolver(&self) -> Option<&HeightResolver> {
        self.height_resolver
            .has_providers()
            .then_some(&self.height_resolver)
    }

    /// Wall height in blocks (and the tall-building flag) from an external provider
    /// (GSI-3D / PLATEAU), looked up at the footprint centroid.
    ///
    /// None when no provider is registered, no provider knows the building, or the
    /// element is a `building:part` (parts carry their own heights in OSM).
    pub fn external_building_height(&self, way: &ProcessedWay, scale: f64) -> Option<(i32, bool)> {
        let resolver = self.active_height_resolver()?;
        if way.nodes.is_empty()
            || !way.tags.contains_key("building")
            || way.tags.contains_key("building:part")
        {
            return None;
        }
        let n = way.nodes.len() as f64;
        let cx = way.nodes.iter().map(|nd| nd.x as f64).sum::<f64>() / n;
        let cz = way.nodes.iter().map(|nd| nd.z as f64).sum::<f64>() / n;
        let height_m = resolver.resolve_mc(cx as i32, cz as i32)?.height_m;
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
