//! GSI (国土地理院) Building Data Fetcher
//!
//! Downloads building polygons from GSI's optimal vector tiles (optimal_bvmap),
//! caches them locally, and converts to OsmData format for Arnis world generation.
//!
//! Data source: https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/{z}/{x}/{y}.pbf
//! License: Free with attribution ("国土地理院")

use crate::coordinate_system::geographic::LLBBox;
use crate::osm_parser::{OsmData, OsmElement};
use colored::Colorize;
use reqwest::blocking::Client;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const TILE_URL: &str = "https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/{z}/{x}/{y}.pbf";
const ZOOM: u32 = 16;
const GSI_NODE_ID_BASE: u64 = 4_000_000_000; // High IDs to avoid OSM collision
const GSI_WAY_ID_BASE: u64 = 5_000_000_000;

// --- MVT Protobuf Definitions ---
// Mapbox Vector Tile specification: https://github.com/mapbox/vector-tile-spec

mod mvt {
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct Tile {
        #[prost(message, repeated, tag = "3")]
        pub layers: Vec<Layer>,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct Layer {
        #[prost(string, required, tag = "1")]
        pub name: String,
        #[prost(message, repeated, tag = "2")]
        pub features: Vec<Feature>,
        #[prost(string, repeated, tag = "3")]
        pub keys: Vec<String>,
        #[prost(message, repeated, tag = "4")]
        pub values: Vec<Value>,
        #[prost(uint32, optional, tag = "5", default = "4096")]
        pub extent: Option<u32>,
        #[prost(uint32, optional, tag = "15", default = "1")]
        pub version: Option<u32>,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct Feature {
        #[prost(uint64, optional, tag = "1")]
        pub id: Option<u64>,
        #[prost(uint32, repeated, packed = "true", tag = "2")]
        pub tags: Vec<u32>,
        #[prost(enumeration = "GeomType", optional, tag = "3")]
        pub r#type: Option<i32>,
        #[prost(uint32, repeated, packed = "true", tag = "4")]
        pub geometry: Vec<u32>,
    }

    #[derive(Clone, PartialEq, prost::Message)]
    pub struct Value {
        #[prost(string, optional, tag = "1")]
        pub string_value: Option<String>,
        #[prost(float, optional, tag = "2")]
        pub float_value: Option<f32>,
        #[prost(double, optional, tag = "3")]
        pub double_value: Option<f64>,
        #[prost(int64, optional, tag = "4")]
        pub int_value: Option<i64>,
        #[prost(uint64, optional, tag = "5")]
        pub uint_value: Option<u64>,
        #[prost(sint64, optional, tag = "6")]
        pub sint_value: Option<i64>,
        #[prost(bool, optional, tag = "7")]
        pub bool_value: Option<bool>,
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, prost::Enumeration)]
    #[repr(i32)]
    pub enum GeomType {
        Unknown = 0,
        Point = 1,
        Linestring = 2,
        Polygon = 3,
    }
}

// --- Tile Math ---

fn lat_lng_to_tile(lat: f64, lng: f64) -> (u32, u32) {
    let n = (1u64 << ZOOM) as f64;
    let x = ((lng + 180.0) / 360.0 * n) as u32;
    let lat_rad = lat.to_radians();
    let y = ((1.0 - (lat_rad.tan() + 1.0 / lat_rad.cos()).ln() / std::f64::consts::PI) / 2.0 * n)
        as u32;
    (x, y)
}

fn tile_pixel_to_lat_lng(
    tile_x: u32,
    tile_y: u32,
    px: f64,
    py: f64,
    extent: u32,
) -> (f64, f64) {
    let n = (1u64 << ZOOM) as f64;
    let ext = extent as f64;
    let lng = (tile_x as f64 + px / ext) / n * 360.0 - 180.0;
    let lat_rad = (std::f64::consts::PI
        * (1.0 - 2.0 * (tile_y as f64 + py / ext) / n))
        .sinh()
        .atan();
    let lat = lat_rad.to_degrees();
    (lat, lng)
}

fn get_tile_range(bbox: &LLBBox) -> Vec<(u32, u32)> {
    let (x1, y1) = lat_lng_to_tile(bbox.max().lat(), bbox.min().lng()); // NW corner
    let (x2, y2) = lat_lng_to_tile(bbox.min().lat(), bbox.max().lng()); // SE corner
    let mut tiles = Vec::new();
    for x in x1..=x2 {
        for y in y1..=y2 {
            tiles.push((x, y));
        }
    }
    tiles
}

// --- Cache ---

fn get_cache_dir() -> PathBuf {
    let base = dirs::cache_dir().unwrap_or_else(|| PathBuf::from("."));
    base.join("arnis").join("gsi_tiles")
}

fn cache_path(tile_x: u32, tile_y: u32) -> PathBuf {
    get_cache_dir()
        .join(ZOOM.to_string())
        .join(tile_x.to_string())
        .join(format!("{tile_y}.pbf"))
}

fn read_cached_tile(tile_x: u32, tile_y: u32) -> Option<Vec<u8>> {
    let path = cache_path(tile_x, tile_y);
    fs::read(&path).ok()
}

fn save_to_cache(tile_x: u32, tile_y: u32, data: &[u8]) {
    let path = cache_path(tile_x, tile_y);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(&path, data);
}

// --- Download ---

fn download_tile(
    client: &Client,
    tile_x: u32,
    tile_y: u32,
) -> Result<Option<Vec<u8>>, Box<dyn std::error::Error>> {
    let url = TILE_URL
        .replace("{z}", &ZOOM.to_string())
        .replace("{x}", &tile_x.to_string())
        .replace("{y}", &tile_y.to_string());

    let resp = client.get(&url).send()?;

    if resp.status().as_u16() == 404 {
        return Ok(None); // No tile (ocean, etc.)
    }

    if !resp.status().is_success() {
        return Err(format!("GSI tile {ZOOM}/{tile_x}/{tile_y}: HTTP {}", resp.status()).into());
    }

    let bytes = resp.bytes()?.to_vec();
    Ok(Some(bytes))
}

// --- MVT Geometry Decoding ---

/// Decode MVT geometry commands into rings of (px, py) coordinates
fn decode_geometry(geometry: &[u32]) -> Vec<Vec<(f64, f64)>> {
    let mut rings: Vec<Vec<(f64, f64)>> = Vec::new();
    let mut current_ring: Vec<(f64, f64)> = Vec::new();
    let mut cursor_x: i64 = 0;
    let mut cursor_y: i64 = 0;
    let mut i = 0;

    while i < geometry.len() {
        let cmd_integer = geometry[i];
        let cmd_id = cmd_integer & 0x7;
        let cmd_count = (cmd_integer >> 3) as usize;
        i += 1;

        match cmd_id {
            1 => {
                // MoveTo
                if !current_ring.is_empty() {
                    rings.push(std::mem::take(&mut current_ring));
                }
                for _ in 0..cmd_count {
                    if i + 1 >= geometry.len() {
                        break;
                    }
                    let dx = zigzag_decode(geometry[i]);
                    let dy = zigzag_decode(geometry[i + 1]);
                    cursor_x += dx;
                    cursor_y += dy;
                    current_ring.push((cursor_x as f64, cursor_y as f64));
                    i += 2;
                }
            }
            2 => {
                // LineTo
                for _ in 0..cmd_count {
                    if i + 1 >= geometry.len() {
                        break;
                    }
                    let dx = zigzag_decode(geometry[i]);
                    let dy = zigzag_decode(geometry[i + 1]);
                    cursor_x += dx;
                    cursor_y += dy;
                    current_ring.push((cursor_x as f64, cursor_y as f64));
                    i += 2;
                }
            }
            7 => {
                // ClosePath — close the ring by repeating the first point
                if let Some(&first) = current_ring.first() {
                    current_ring.push(first);
                }
                rings.push(std::mem::take(&mut current_ring));
            }
            _ => {
                // Unknown command, skip
                break;
            }
        }
    }

    if !current_ring.is_empty() {
        rings.push(current_ring);
    }

    rings
}

fn zigzag_decode(n: u32) -> i64 {
    ((n >> 1) as i64) ^ (-((n & 1) as i64))
}

// --- Building Extraction ---

struct GsiBuilding {
    coords: Vec<(f64, f64)>, // (lat, lng) pairs
    vt_code: u32,
}

fn extract_buildings_from_tile(
    pbf_data: &[u8],
    tile_x: u32,
    tile_y: u32,
) -> Vec<GsiBuilding> {
    use prost::Message;

    let tile = match mvt::Tile::decode(pbf_data) {
        Ok(t) => t,
        Err(e) => {
            eprintln!(
                "{} Failed to decode GSI tile {}/{}/{}: {}",
                "Warning:".yellow().bold(),
                ZOOM,
                tile_x,
                tile_y,
                e
            );
            return Vec::new();
        }
    };

    let mut buildings = Vec::new();

    for layer in &tile.layers {
        if layer.name != "BldA" {
            continue;
        }

        let extent = layer.extent.unwrap_or(4096);

        for feature in &layer.features {
            // Only process polygons
            if feature.r#type != Some(mvt::GeomType::Polygon as i32) {
                continue;
            }

            // Extract vt_code from tags
            let mut vt_code: u32 = 3101;
            let tags = &feature.tags;
            let mut t = 0;
            while t + 1 < tags.len() {
                let key_idx = tags[t] as usize;
                let val_idx = tags[t + 1] as usize;
                if key_idx < layer.keys.len()
                    && val_idx < layer.values.len()
                    && layer.keys[key_idx] == "vt_code"
                {
                    let val = &layer.values[val_idx];
                    if let Some(v) = val.int_value {
                        vt_code = v as u32;
                    } else if let Some(v) = val.uint_value {
                        vt_code = v as u32;
                    } else if let Some(v) = val.float_value {
                        vt_code = v as u32;
                    } else if let Some(v) = val.double_value {
                        vt_code = v as u32;
                    }
                    break;
                }
                t += 2;
            }

            // Decode geometry
            let rings = decode_geometry(&feature.geometry);

            // Each ring becomes a building (use only outer rings)
            for ring in &rings {
                if ring.len() < 4 {
                    continue; // Need at least 3 unique points + closing point
                }

                // Convert tile-local coordinates to lat/lng
                let lat_lng_coords: Vec<(f64, f64)> = ring
                    .iter()
                    .map(|(px, py)| tile_pixel_to_lat_lng(tile_x, tile_y, *px, *py, extent))
                    .collect();

                buildings.push(GsiBuilding {
                    coords: lat_lng_coords,
                    vt_code,
                });
            }
        }
    }

    buildings
}

// --- Bbox Filtering ---

fn building_centroid(building: &GsiBuilding) -> (f64, f64) {
    let points = if building.coords.len() > 1
        && building.coords.first() == building.coords.last()
    {
        &building.coords[..building.coords.len() - 1]
    } else {
        &building.coords
    };

    if points.is_empty() {
        return (0.0, 0.0);
    }

    let avg_lat = points.iter().map(|p| p.0).sum::<f64>() / points.len() as f64;
    let avg_lng = points.iter().map(|p| p.1).sum::<f64>() / points.len() as f64;
    (avg_lat, avg_lng)
}

fn is_in_bbox(lat: f64, lng: f64, bbox: &LLBBox) -> bool {
    lat >= bbox.min().lat()
        && lat <= bbox.max().lat()
        && lng >= bbox.min().lng()
        && lng <= bbox.max().lng()
}

// --- Convert to OsmData ---

fn buildings_to_osm_data(buildings: &[GsiBuilding]) -> OsmData {
    let mut elements: Vec<OsmElement> = Vec::new();
    let mut node_id = GSI_NODE_ID_BASE;
    let mut way_id = GSI_WAY_ID_BASE;

    for building in buildings {
        let mut way_node_ids = Vec::new();

        for &(lat, lng) in &building.coords {
            elements.push(OsmElement {
                r#type: "node".to_string(),
                id: node_id,
                lat: Some(lat),
                lon: Some(lng),
                nodes: None,
                tags: None,
                members: Vec::new(),
            });
            way_node_ids.push(node_id);
            node_id += 1;
        }

        let mut tags = HashMap::new();
        tags.insert("building".to_string(), "yes".to_string());
        tags.insert("source".to_string(), "GSI optimal_bvmap".to_string());

        if building.vt_code == 3103 {
            tags.insert("building:levels".to_string(), "5".to_string());
        }

        elements.push(OsmElement {
            r#type: "way".to_string(),
            id: way_id,
            lat: None,
            lon: None,
            nodes: Some(way_node_ids),
            tags: Some(tags),
            members: Vec::new(),
        });
        way_id += 1;
    }

    OsmData::from_elements(elements)
}

// --- Public API ---

/// Fetch GSI building data for the given bbox and return as OsmData.
/// Uses local cache: tiles are downloaded once and stored in the system cache directory.
pub fn fetch_gsi_buildings(
    bbox: LLBBox,
) -> Result<OsmData, Box<dyn std::error::Error>> {
    let tiles = get_tile_range(&bbox);
    let total = tiles.len();

    println!(
        "{}",
        format!(
            "GSI building data: {} tile(s) to process (z={ZOOM})",
            total
        )
        .bright_white()
        .bold()
    );

    let client = Client::builder()
        .timeout(Duration::from_secs(30))
        .user_agent("arnis-gsi-import/1.0")
        .build()?;

    let mut all_buildings: Vec<GsiBuilding> = Vec::new();

    for (i, (tx, ty)) in tiles.iter().enumerate() {
        // Try cache first
        let pbf_data = if let Some(cached) = read_cached_tile(*tx, *ty) {
            println!(
                "  [{}/{}] Tile {ZOOM}/{tx}/{ty} (cached)",
                i + 1,
                total
            );
            cached
        } else {
            println!(
                "  [{}/{}] Tile {ZOOM}/{tx}/{ty} downloading...",
                i + 1,
                total
            );
            match download_tile(&client, *tx, *ty)? {
                Some(data) => {
                    save_to_cache(*tx, *ty, &data);
                    data
                }
                None => {
                    println!("    → no data (ocean/empty area)");
                    continue;
                }
            }
        };

        let buildings = extract_buildings_from_tile(&pbf_data, *tx, *ty);
        println!("    → {} buildings", buildings.len());
        all_buildings.extend(buildings);
    }

    println!("GSI total buildings fetched: {}", all_buildings.len());

    // Filter to bbox
    let in_bbox: Vec<GsiBuilding> = all_buildings
        .into_iter()
        .filter(|b| {
            let (lat, lng) = building_centroid(b);
            is_in_bbox(lat, lng, &bbox)
        })
        .collect();

    println!(
        "GSI buildings within bbox: {}",
        in_bbox.len()
    );

    let osm_data = buildings_to_osm_data(&in_bbox);

    println!(
        "{}",
        format!(
            "GSI data ready: {} nodes, {} ways",
            osm_data.elements.iter().filter(|e| e.r#type == "node").count(),
            osm_data.elements.iter().filter(|e| e.r#type == "way").count(),
        )
        .green()
        .bold()
    );

    Ok(osm_data)
}

/// Return the cache directory path (for user documentation)
#[allow(dead_code)]
pub fn get_gsi_cache_path() -> PathBuf {
    get_cache_dir()
}
