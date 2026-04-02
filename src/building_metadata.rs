use serde::Serialize;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;

/// Metadata for a single generated building, used for post-processing by external tools.
#[derive(Debug, Serialize)]
pub struct BuildingMetadata {
    /// OSM element ID
    pub osm_id: u64,
    /// Building name from OSM tags (if available)
    pub name: Option<String>,
    /// Building type (e.g. "residential", "commercial", "yes")
    pub building_type: String,
    /// All OSM tags for this building
    pub tags: HashMap<String, String>,
    /// Minecraft coordinate bounding box
    pub min_x: i32,
    pub max_x: i32,
    pub min_z: i32,
    pub max_z: i32,
    /// Building height in blocks
    pub height: i32,
    /// Y coordinate of the building base
    pub base_y: i32,
    /// Floor area coordinates (all x,z pairs that make up the footprint)
    pub floor_area: Vec<[i32; 2]>,
}

/// Thread-safe collector for building metadata during world generation.
pub struct BuildingMetadataCollector {
    buildings: Mutex<Vec<BuildingMetadata>>,
}

impl BuildingMetadataCollector {
    pub fn new() -> Self {
        Self {
            buildings: Mutex::new(Vec::new()),
        }
    }

    /// Add a building's metadata to the collection.
    pub fn add(&self, metadata: BuildingMetadata) {
        self.buildings.lock().unwrap().push(metadata);
    }

    /// Save all collected building metadata to a JSON file.
    pub fn save_to_json(&self, output_dir: &Path) -> Result<(), String> {
        let buildings = self.buildings.lock().unwrap();
        if buildings.is_empty() {
            return Ok(());
        }

        let json_path = output_dir.join("buildings.json");
        let json = serde_json::to_string_pretty(&*buildings)
            .map_err(|e| format!("Failed to serialize building metadata: {e}"))?;
        std::fs::write(&json_path, json)
            .map_err(|e| format!("Failed to write buildings.json: {e}"))?;

        println!(
            "Saved {} building metadata entries to {}",
            buildings.len(),
            json_path.display()
        );

        Ok(())
    }
}
