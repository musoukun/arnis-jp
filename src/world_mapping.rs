use serde::Serialize;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;

/// Complete mapping between OSM data and Minecraft world coordinates.
/// Generated alongside the world for use by external post-processing tools.
#[derive(Debug, Serialize)]
pub struct WorldMapping {
    /// The geographic bounding box used for generation [min_lat, min_lng, max_lat, max_lng]
    pub bbox: [f64; 4],
    /// Scale factor (blocks per meter)
    pub scale: f64,
    /// Computed scale factor for X axis (longitude → X)
    pub scale_factor_x: f64,
    /// Computed scale factor for Z axis (latitude → Z)
    pub scale_factor_z: f64,
    /// Ground Y level in the Minecraft world
    pub ground_level: i32,
    /// Min latitude of bbox (for reverse mapping)
    pub min_lat: f64,
    /// Min longitude of bbox (for reverse mapping)
    pub min_lng: f64,
    /// Latitude span
    pub len_lat: f64,
    /// Longitude span
    pub len_lng: f64,
    /// All mapped entities (buildings, roads, etc.)
    pub entities: Vec<EntityMapping>,
}

/// A single OSM entity mapped to Minecraft coordinates.
#[derive(Debug, Serialize)]
pub struct EntityMapping {
    /// OSM element ID
    pub osm_id: u64,
    /// Entity type: "building", "road", "landuse", "natural", "amenity", "barrier", etc.
    pub entity_type: String,
    /// Name from OSM tags (if available)
    pub name: Option<String>,
    /// All OSM tags
    pub tags: HashMap<String, String>,
    /// Minecraft coordinate bounding box
    pub mc_min_x: i32,
    pub mc_max_x: i32,
    pub mc_min_z: i32,
    pub mc_max_z: i32,
}

/// Thread-safe collector for entity mappings during world generation.
pub struct WorldMappingCollector {
    entities: Mutex<Vec<EntityMapping>>,
}

impl WorldMappingCollector {
    pub fn new() -> Self {
        Self {
            entities: Mutex::new(Vec::new()),
        }
    }

    /// Add an entity mapping.
    pub fn add(&self, entity: EntityMapping) {
        self.entities.lock().unwrap().push(entity);
    }

    /// Save the complete world mapping to JSON.
    pub fn save_to_json(
        &self,
        output_dir: &Path,
        bbox: [f64; 4],
        scale: f64,
        scale_factor_x: f64,
        scale_factor_z: f64,
        ground_level: i32,
        min_lat: f64,
        min_lng: f64,
        len_lat: f64,
        len_lng: f64,
    ) -> Result<(), String> {
        let entities = self.entities.lock().unwrap();

        let mapping = WorldMapping {
            bbox,
            scale,
            scale_factor_x,
            scale_factor_z,
            ground_level,
            min_lat,
            min_lng,
            len_lat,
            len_lng,
            entities: entities.clone(),
        };

        // Need Clone on EntityMapping for this
        let json_path = output_dir.join("world_mapping.json");
        let json = serde_json::to_string_pretty(&mapping)
            .map_err(|e| format!("Failed to serialize world mapping: {e}"))?;
        std::fs::write(&json_path, json)
            .map_err(|e| format!("Failed to write world_mapping.json: {e}"))?;

        println!(
            "Saved world mapping ({} entities) to {}",
            entities.len(),
            json_path.display()
        );

        Ok(())
    }
}

// EntityMapping needs Clone for save_to_json
impl Clone for EntityMapping {
    fn clone(&self) -> Self {
        Self {
            osm_id: self.osm_id,
            entity_type: self.entity_type.clone(),
            name: self.name.clone(),
            tags: self.tags.clone(),
            mc_min_x: self.mc_min_x,
            mc_max_x: self.mc_max_x,
            mc_min_z: self.mc_min_z,
            mc_max_z: self.mc_max_z,
        }
    }
}
