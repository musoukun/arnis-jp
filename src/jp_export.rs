/// Japan-specific export context for metadata / mapping JSON output.
///
/// Bundles `BuildingMetadataCollector` and `WorldMappingCollector`
/// together with the coordinate transform parameters that only
/// exist for `world_mapping.json`.  Keeping these separate from
/// the upstream `GenerationOptions` avoids merge conflicts when
/// upstream adds or changes fields.

use crate::building_metadata::BuildingMetadataCollector;
use crate::coordinate_system::geographic::LLBBox;
use crate::coordinate_system::transformation::CoordTransformer;
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
