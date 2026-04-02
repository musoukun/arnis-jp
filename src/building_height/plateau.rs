//! PLATEAU (国土交通省 3D都市モデル) height provider.
//!
//! Queries the PLATEAU GraphQL Data Catalog API to find building datasets,
//! downloads 3D Tiles (b3dm), and extracts `bldg:measuredHeight` from the
//! Batch Table. Coverage: ~350 cities across Japan (as of 2026).
//!
//! # Data flow
//!
//! ```text
//! bbox → prefecture code → GraphQL query → tileset.json URLs
//!   → filter tiles by bbox → download b3dm → parse Batch Table
//!   → Vec<PlateauBuilding> { lat, lng, height_m }
//! ```

use super::b3dm;
use super::{HeightProvider, HeightResult};
use serde_json::Value;

const GRAPHQL_URL: &str = "https://api.plateauview.mlit.go.jp/datacatalog/graphql";

/// Maximum distance (degrees) for centroid matching (~30 m).
const MATCH_THRESHOLD_DEG: f64 = 0.0003;
const MATCH_THRESHOLD_SQ: f64 = MATCH_THRESHOLD_DEG * MATCH_THRESHOLD_DEG;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// A building with height and position extracted from PLATEAU 3D Tiles.
#[derive(Debug, Clone)]
struct PlateauBuilding {
    lat: f64,
    lng: f64,
    height_m: f64,
}

/// PLATEAU height provider backed by pre-fetched building data.
pub struct PlateauProvider {
    buildings: Vec<PlateauBuilding>,
}

impl PlateauProvider {
    /// Fetch PLATEAU data for the given bounding box.
    ///
    /// 1. Determines the prefecture from the bbox center
    /// 2. Queries the GraphQL catalog for bldg datasets
    /// 3. Downloads tileset.json and filters tiles by bbox
    /// 4. Parses b3dm tiles for measuredHeight
    pub fn from_bbox(
        min_lat: f64,
        min_lng: f64,
        max_lat: f64,
        max_lng: f64,
    ) -> Result<Self, String> {
        let center_lat = (min_lat + max_lat) / 2.0;
        let center_lng = (min_lng + max_lng) / 2.0;

        let pref_code = bbox_to_prefecture_code(center_lat, center_lng)
            .ok_or("Could not determine prefecture from bbox coordinates")?;

        println!(
            "[PLATEAU] Searching for building data in prefecture {}...",
            pref_code
        );

        // Query GraphQL for building datasets in this prefecture
        let tileset_urls = query_building_datasets(&pref_code)?;
        if tileset_urls.is_empty() {
            return Err(format!(
                "No PLATEAU building data found for prefecture {}",
                pref_code
            ));
        }

        println!(
            "[PLATEAU] Found {} dataset(s), downloading tiles...",
            tileset_urls.len()
        );

        let bbox_rad = BBoxRadians {
            west: min_lng.to_radians(),
            south: min_lat.to_radians(),
            east: max_lng.to_radians(),
            north: max_lat.to_radians(),
        };

        let mut buildings = Vec::new();

        for url in &tileset_urls {
            match fetch_buildings_from_tileset(url, &bbox_rad) {
                Ok(mut blds) => buildings.append(&mut blds),
                Err(e) => {
                    eprintln!("[PLATEAU] Warning: failed to process {}: {}", url, e);
                }
            }
        }

        println!("[PLATEAU] Loaded {} buildings with height data", buildings.len());

        if buildings.is_empty() {
            return Err("PLATEAU data found but no buildings overlap the bbox".into());
        }

        Ok(Self { buildings })
    }
}

impl HeightProvider for PlateauProvider {
    fn lookup(&self, lat: f64, lng: f64) -> Option<HeightResult> {
        let mut best: Option<(f64, &PlateauBuilding)> = None;

        for bld in &self.buildings {
            let dlat = bld.lat - lat;
            let dlng = bld.lng - lng;
            let dist_sq = dlat * dlat + dlng * dlng;

            if dist_sq > MATCH_THRESHOLD_SQ {
                continue;
            }

            match best {
                Some((d, _)) if dist_sq < d => best = Some((dist_sq, bld)),
                None => best = Some((dist_sq, bld)),
                _ => {}
            }
        }

        best.map(|(_, bld)| HeightResult {
            height_m: bld.height_m,
            ground_elv_m: None,
            source: "PLATEAU",
        })
    }

    fn name(&self) -> &'static str {
        "PLATEAU"
    }
}

// ---------------------------------------------------------------------------
// GraphQL API
// ---------------------------------------------------------------------------

/// Query PLATEAU GraphQL for building (bldg) dataset tileset.json URLs.
fn query_building_datasets(pref_code: &str) -> Result<Vec<String>, String> {
    let query = format!(
        r#"{{
  datasets(input: {{ areaCodes: ["{}"], includeTypes: ["bldg"] }}) {{
    ... on PlateauDataset {{
      id
      items {{
        ... on PlateauDatasetItem {{
          url
          format
          lod
        }}
      }}
    }}
  }}
}}"#,
        pref_code
    );

    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| format!("HTTP client error: {e}"))?;

    let resp = client
        .post(GRAPHQL_URL)
        .json(&serde_json::json!({ "query": query }))
        .send()
        .map_err(|e| format!("PLATEAU API request failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("PLATEAU API returned {}", resp.status()));
    }

    let body: Value = resp
        .json()
        .map_err(|e| format!("PLATEAU API response parse error: {e}"))?;

    // Extract tileset.json URLs (prefer LOD1 for measuredHeight, smaller data)
    let mut urls = Vec::new();
    if let Some(datasets) = body.pointer("/data/datasets").and_then(|v| v.as_array()) {
        for ds in datasets {
            if let Some(items) = ds.get("items").and_then(|v| v.as_array()) {
                // Find LOD1 CESIUM3DTILES item (has measuredHeight, smaller than LOD2)
                let best_item = items
                    .iter()
                    .filter(|item| {
                        item.get("format").and_then(|v| v.as_str()) == Some("CESIUM3DTILES")
                    })
                    .min_by_key(|item| {
                        // Prefer LOD1, then LOD2
                        item.get("lod").and_then(|v| v.as_u64()).unwrap_or(99)
                    });

                if let Some(item) = best_item {
                    if let Some(url) = item.get("url").and_then(|v| v.as_str()) {
                        urls.push(url.to_string());
                    }
                }
            }
        }
    }

    Ok(urls)
}

// ---------------------------------------------------------------------------
// Tileset parsing + b3dm download
// ---------------------------------------------------------------------------

/// Bounding box in radians (tileset.json uses radians for `region` volumes).
struct BBoxRadians {
    west: f64,
    south: f64,
    east: f64,
    north: f64,
}

/// Fetch buildings from a single tileset.json, filtering by bbox.
fn fetch_buildings_from_tileset(
    tileset_url: &str,
    bbox: &BBoxRadians,
) -> Result<Vec<PlateauBuilding>, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .map_err(|e| format!("HTTP client error: {e}"))?;

    // Fetch tileset.json
    let resp = client
        .get(tileset_url)
        .send()
        .map_err(|e| format!("Failed to fetch tileset.json: {e}"))?;

    let tileset: Value = resp
        .json()
        .map_err(|e| format!("tileset.json parse error: {e}"))?;

    // Check if root bounding volume overlaps bbox
    let root = tileset
        .get("root")
        .ok_or("tileset.json missing 'root'")?;

    if !region_overlaps_bbox(root, bbox) {
        return Ok(Vec::new());
    }

    // Collect b3dm tile URIs that overlap bbox
    let base_url = tileset_url
        .rsplit_once('/')
        .map(|(base, _)| base)
        .unwrap_or(tileset_url);

    let mut tile_entries: Vec<(String, [f64; 4])> = Vec::new();
    collect_overlapping_tiles(root, base_url, bbox, &mut tile_entries);

    let mut buildings = Vec::new();

    for (tile_url, tile_region) in &tile_entries {
        // Tile center in degrees (for approximate building positions)
        let tile_center_lat = ((tile_region[1] + tile_region[3]) / 2.0).to_degrees();
        let tile_center_lng = ((tile_region[0] + tile_region[2]) / 2.0).to_degrees();

        match client.get(tile_url.as_str()).send() {
            Ok(resp) if resp.status().is_success() => {
                if let Ok(bytes) = resp.bytes() {
                    match b3dm::parse_b3dm_heights(&bytes) {
                        Ok(b3dm_buildings) => {
                            for bld in b3dm_buildings {
                                buildings.push(PlateauBuilding {
                                    lat: tile_center_lat,
                                    lng: tile_center_lng,
                                    height_m: bld.measured_height,
                                });
                            }
                        }
                        Err(e) => {
                            eprintln!("[PLATEAU] b3dm parse warning: {}", e);
                        }
                    }
                }
            }
            Ok(resp) => {
                eprintln!("[PLATEAU] Tile download failed: {} {}", tile_url, resp.status());
            }
            Err(e) => {
                eprintln!("[PLATEAU] Tile download error: {}", e);
            }
        }
    }

    Ok(buildings)
}

/// Recursively collect b3dm tile URLs whose bounding volume overlaps the bbox.
fn collect_overlapping_tiles(
    node: &Value,
    base_url: &str,
    bbox: &BBoxRadians,
    out: &mut Vec<(String, [f64; 4])>,
) {
    // Check if this node overlaps
    if !region_overlaps_bbox(node, bbox) {
        return;
    }

    // Extract region for position info
    let region = extract_region(node).unwrap_or([0.0; 6]);

    // If this node has content, record it
    if let Some(content) = node.get("content") {
        if let Some(uri) = content
            .get("uri")
            .or_else(|| content.get("url"))
            .and_then(|v| v.as_str())
        {
            if uri.ends_with(".b3dm") {
                let full_url = if uri.starts_with("http") {
                    uri.to_string()
                } else {
                    format!("{}/{}", base_url, uri)
                };
                out.push((full_url, [region[0], region[1], region[2], region[3]]));
            }
        }
    }

    // Recurse into children
    if let Some(children) = node.get("children").and_then(|v| v.as_array()) {
        for child in children {
            collect_overlapping_tiles(child, base_url, bbox, out);
        }
    }
}

/// Check if a tileset node's `boundingVolume.region` overlaps the given bbox.
fn region_overlaps_bbox(node: &Value, bbox: &BBoxRadians) -> bool {
    let region = match extract_region(node) {
        Some(r) => r,
        None => return true, // No region info → assume overlap (conservative)
    };

    let (west, south, east, north) = (region[0], region[1], region[2], region[3]);

    // Standard AABB overlap test
    !(east < bbox.west || west > bbox.east || north < bbox.south || south > bbox.north)
}

/// Extract [west, south, east, north, minH, maxH] from `boundingVolume.region`.
fn extract_region(node: &Value) -> Option<[f64; 6]> {
    let arr = node
        .pointer("/boundingVolume/region")
        .and_then(|v| v.as_array())?;

    if arr.len() < 6 {
        return None;
    }

    Some([
        arr[0].as_f64()?,
        arr[1].as_f64()?,
        arr[2].as_f64()?,
        arr[3].as_f64()?,
        arr[4].as_f64()?,
        arr[5].as_f64()?,
    ])
}

// ---------------------------------------------------------------------------
// Prefecture lookup
// ---------------------------------------------------------------------------

/// Approximate center coordinates for Japan's 47 prefectures.
/// Format: (code, lat, lng)
const PREFECTURES: &[(u8, f64, f64)] = &[
    (1, 43.06, 141.35),   // 北海道
    (2, 40.82, 140.74),   // 青森
    (3, 39.70, 141.15),   // 岩手
    (4, 38.27, 140.87),   // 宮城
    (5, 39.72, 140.10),   // 秋田
    (6, 38.24, 140.34),   // 山形
    (7, 37.75, 140.47),   // 福島
    (8, 36.34, 140.45),   // 茨城
    (9, 36.57, 139.88),   // 栃木
    (10, 36.39, 139.06),  // 群馬
    (11, 35.86, 139.65),  // 埼玉
    (12, 35.61, 140.12),  // 千葉
    (13, 35.69, 139.69),  // 東京
    (14, 35.45, 139.64),  // 神奈川
    (15, 37.90, 139.02),  // 新潟
    (16, 36.70, 137.21),  // 富山
    (17, 36.59, 136.63),  // 石川
    (18, 36.07, 136.22),  // 福井
    (19, 35.66, 138.57),  // 山梨
    (20, 36.23, 138.18),  // 長野
    (21, 35.39, 136.72),  // 岐阜
    (22, 34.98, 138.38),  // 静岡
    (23, 35.18, 136.91),  // 愛知
    (24, 34.73, 136.51),  // 三重
    (25, 35.00, 135.87),  // 滋賀
    (26, 35.02, 135.76),  // 京都
    (27, 34.69, 135.52),  // 大阪
    (28, 34.69, 135.18),  // 兵庫
    (29, 34.69, 135.83),  // 奈良
    (30, 33.95, 135.17),  // 和歌山
    (31, 35.50, 134.24),  // 鳥取
    (32, 35.47, 133.05),  // 島根
    (33, 34.66, 133.93),  // 岡山
    (34, 34.40, 132.46),  // 広島
    (35, 34.19, 131.47),  // 山口
    (36, 34.07, 134.56),  // 徳島
    (37, 34.34, 134.04),  // 香川
    (38, 33.84, 132.77),  // 愛媛
    (39, 33.56, 133.53),  // 高知
    (40, 33.59, 130.42),  // 福岡
    (41, 33.25, 130.30),  // 佐賀
    (42, 32.74, 129.87),  // 長崎
    (43, 32.79, 130.74),  // 熊本
    (44, 33.24, 131.61),  // 大分
    (45, 31.91, 131.42),  // 宮崎
    (46, 31.56, 130.56),  // 鹿児島
    (47, 26.34, 127.78),  // 沖縄
];

/// Map a lat/lng to the nearest Japanese prefecture code (2-digit string).
fn bbox_to_prefecture_code(lat: f64, lng: f64) -> Option<String> {
    // Quick bounds check — roughly Japan
    if lat < 24.0 || lat > 46.0 || lng < 122.0 || lng > 154.0 {
        return None;
    }

    let (code, _, _) = PREFECTURES
        .iter()
        .min_by(|(_, a_lat, a_lng), (_, b_lat, b_lng)| {
            let da = (a_lat - lat).powi(2) + (a_lng - lng).powi(2);
            let db = (b_lat - lat).powi(2) + (b_lng - lng).powi(2);
            da.partial_cmp(&db).unwrap()
        })?;

    Some(format!("{:02}", code))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prefecture_lookup_tokyo() {
        assert_eq!(
            bbox_to_prefecture_code(35.68, 139.77),
            Some("13".to_string())
        );
    }

    #[test]
    fn test_prefecture_lookup_osaka() {
        assert_eq!(
            bbox_to_prefecture_code(34.69, 135.50),
            Some("27".to_string())
        );
    }

    #[test]
    fn test_prefecture_lookup_outside_japan() {
        assert!(bbox_to_prefecture_code(0.0, 0.0).is_none());
    }

    #[test]
    fn test_region_overlap() {
        let bbox = BBoxRadians {
            west: 139.7_f64.to_radians(),
            south: 35.6_f64.to_radians(),
            east: 139.8_f64.to_radians(),
            north: 35.7_f64.to_radians(),
        };

        // Overlapping region
        let node = serde_json::json!({
            "boundingVolume": {
                "region": [
                    139.75_f64.to_radians(),
                    35.65_f64.to_radians(),
                    139.85_f64.to_radians(),
                    35.75_f64.to_radians(),
                    0.0, 100.0
                ]
            }
        });
        assert!(region_overlaps_bbox(&node, &bbox));

        // Non-overlapping region (far away)
        let node2 = serde_json::json!({
            "boundingVolume": {
                "region": [
                    130.0_f64.to_radians(),
                    33.0_f64.to_radians(),
                    131.0_f64.to_radians(),
                    34.0_f64.to_radians(),
                    0.0, 100.0
                ]
            }
        });
        assert!(!region_overlaps_bbox(&node2, &bbox));
    }

    #[test]
    fn test_region_no_bounding_volume_is_conservative() {
        let bbox = BBoxRadians {
            west: 0.0,
            south: 0.0,
            east: 1.0,
            north: 1.0,
        };
        let node = serde_json::json!({});
        // No bounding volume → assume overlap (conservative)
        assert!(region_overlaps_bbox(&node, &bbox));
    }
}
