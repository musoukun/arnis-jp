//! arnis-jp: GSI (国土地理院) DEM PNG tile provider (`--gsi`, Japan only).
//!
//! Pixel decoding, URL and no-data rules live in `crate::gsi_elevation`; this file only
//! adapts them to the upstream `ElevationProvider` interface (fetch tiles, bilinear-sample
//! them onto the requested grid). Tiles that do not exist (sea, outside Japan) stay NaN, and
//! the caller's fallback chain moves on to the next provider when most of the grid is empty.

use super::tile_math::{blend_finite_samples, MAX_TILES_PER_FETCH};
use crate::coordinate_system::geographic::LLBBox;
use crate::elevation::cache::get_cache_dir;
use crate::elevation::provider::{ElevationProvider, RawElevationGrid};
use crate::gsi_elevation;
use rayon::prelude::*;
use std::collections::HashMap;
use std::path::Path;

const MIN_ZOOM: u8 = 10;
const MAX_CONCURRENT_DOWNLOADS: usize = 8;
const TILE_DOWNLOAD_MAX_RETRIES: u32 = 3;
const TILE_DOWNLOAD_RETRY_BASE_DELAY_MS: u64 = 500;
const TILE_SIZE: usize = 256;

/// One decoded tile: row-major heights in metres, NaN where the tile has no data.
type TileHeights = Vec<f64>;

pub struct GsiDem;

impl ElevationProvider for GsiDem {
    fn name(&self) -> &'static str {
        "gsi"
    }

    fn native_resolution_m(&self) -> f64 {
        10.0
    }

    fn fetch_raw(
        &self,
        bbox: &LLBBox,
        grid_width: usize,
        grid_height: usize,
    ) -> Result<RawElevationGrid, Box<dyn std::error::Error>> {
        let zoom = calculate_zoom_level(bbox);
        let tiles = get_tile_coordinates(bbox, zoom);

        let cache_dir = get_cache_dir(self.name());
        std::fs::create_dir_all(&cache_dir)?;

        let client = reqwest::blocking::Client::builder()
            .user_agent(concat!("arnis/", env!("CARGO_PKG_VERSION")))
            .build()?;

        println!(
            "Using {} elevation data (国土地理院 標高タイル): {} tiles at z={zoom} (up to {MAX_CONCURRENT_DOWNLOADS} concurrent)...",
            gsi_elevation::source_name(),
            tiles.len()
        );

        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(MAX_CONCURRENT_DOWNLOADS)
            .build()
            .map_err(|e| format!("Failed to create thread pool: {e}"))?;

        let downloaded: Vec<((u32, u32), Result<TileHeights, String>)> = pool.install(|| {
            tiles
                .par_iter()
                .map(|&(tx, ty)| {
                    let path = cache_dir.join(format!(
                        "{}{zoom}_x{tx}_y{ty}.png",
                        gsi_elevation::cache_prefix()
                    ));
                    ((tx, ty), fetch_or_load_tile(&client, tx, ty, zoom, &path))
                })
                .collect()
        });

        let mut tile_map: HashMap<(u32, u32), TileHeights> = HashMap::new();
        for (key, result) in downloaded {
            match result {
                Ok(heights) => {
                    tile_map.insert(key, heights);
                }
                Err(e) => eprintln!("Warning: Failed to fetch GSI DEM tile {key:?}: {e}"),
            }
        }

        let n = 2.0_f64.powi(zoom as i32);
        let heights_meters: Vec<Vec<f64>> = (0..grid_height)
            .into_par_iter()
            .map(|gy| {
                let mut row = vec![f64::NAN; grid_width];
                for (gx, cell) in row.iter_mut().enumerate() {
                    let lat = bbox.max().lat()
                        - (gy as f64 / (grid_height - 1).max(1) as f64)
                            * (bbox.max().lat() - bbox.min().lat());
                    let lng = bbox.min().lng()
                        + (gx as f64 / (grid_width - 1).max(1) as f64)
                            * (bbox.max().lng() - bbox.min().lng());

                    let fx = (lng + 180.0) / 360.0 * n * TILE_SIZE as f64;
                    let fy = (1.0 - lat.to_radians().tan().asinh() / std::f64::consts::PI) / 2.0
                        * n
                        * TILE_SIZE as f64;
                    let n_tiles = n as i64;
                    let tile_x =
                        ((fx / TILE_SIZE as f64).floor() as i64).clamp(0, n_tiles - 1) as u32;
                    let tile_y =
                        ((fy / TILE_SIZE as f64).floor() as i64).clamp(0, n_tiles - 1) as u32;
                    let px = fx - tile_x as f64 * TILE_SIZE as f64;
                    let py = fy - tile_y as f64 * TILE_SIZE as f64;

                    let x0 = px.floor() as i32;
                    let y0 = py.floor() as i32;
                    let dx = px - x0 as f64;
                    let dy = py - y0 as f64;

                    *cell = blend_finite_samples(
                        sample(&tile_map, tile_x, tile_y, x0, y0),
                        sample(&tile_map, tile_x, tile_y, x0 + 1, y0),
                        sample(&tile_map, tile_x, tile_y, x0, y0 + 1),
                        sample(&tile_map, tile_x, tile_y, x0 + 1, y0 + 1),
                        dx,
                        dy,
                    );
                }
                row
            })
            .collect();

        Ok(RawElevationGrid { heights_meters })
    }
}

/// Height at a tile pixel (crossing into the neighbouring tile when out of range), NaN when
/// the tile is missing or the pixel is no-data.
fn sample(map: &HashMap<(u32, u32), TileHeights>, tx0: u32, ty0: u32, px: i32, py: i32) -> f64 {
    let size = TILE_SIZE as i32;
    let (tx, x) = if px < 0 {
        (tx0.wrapping_sub(1), px + size)
    } else if px >= size {
        (tx0 + 1, px - size)
    } else {
        (tx0, px)
    };
    let (ty, y) = if py < 0 {
        (ty0.wrapping_sub(1), py + size)
    } else if py >= size {
        (ty0 + 1, py - size)
    } else {
        (ty0, py)
    };
    map.get(&(tx, ty))
        .and_then(|t| t.get(y as usize * TILE_SIZE + x as usize))
        .copied()
        .unwrap_or(f64::NAN)
}

/// Decode a GSI DEM PNG into a height grid. No-data (alpha 0, or the raw value that GSI
/// reserves for it) becomes NaN.
fn decode_tile(bytes: &[u8]) -> Result<TileHeights, String> {
    let img = image::load_from_memory(bytes)
        .map_err(|e| e.to_string())?
        .to_rgba8();
    if img.width() as usize != TILE_SIZE || img.height() as usize != TILE_SIZE {
        return Err(format!(
            "unexpected tile size {}x{}",
            img.width(),
            img.height()
        ));
    }
    Ok(img
        .pixels()
        .map(|p| {
            if gsi_elevation::is_nodata(p[3]) || (p[0] == 128 && p[1] == 0 && p[2] == 0) {
                f64::NAN
            } else {
                gsi_elevation::decode_pixel(p[0], p[1], p[2])
            }
        })
        .collect())
}

fn fetch_or_load_tile(
    client: &reqwest::blocking::Client,
    tile_x: u32,
    tile_y: u32,
    zoom: u8,
    tile_path: &Path,
) -> Result<TileHeights, String> {
    if let Ok(bytes) = std::fs::read(tile_path) {
        match decode_tile(&bytes) {
            Ok(h) => return Ok(h),
            Err(e) => {
                eprintln!(
                    "Cached GSI tile {} is invalid ({e}); re-downloading...",
                    tile_path.display()
                );
                let _ = std::fs::remove_file(tile_path);
            }
        }
    }

    let url = gsi_elevation::tile_url()
        .replace("{z}", &zoom.to_string())
        .replace("{x}", &tile_x.to_string())
        .replace("{y}", &tile_y.to_string());

    let mut last_error = String::new();
    for attempt in 0..TILE_DOWNLOAD_MAX_RETRIES {
        if attempt > 0 {
            let delay_ms = TILE_DOWNLOAD_RETRY_BASE_DELAY_MS * (1 << (attempt - 1));
            std::thread::sleep(std::time::Duration::from_millis(delay_ms));
        }
        println!("Fetching tile x={tile_x},y={tile_y},z={zoom} from GSI DEM");
        let result = (|| -> Result<TileHeights, String> {
            let _permit = crate::net::request_permit();
            let response = client.get(&url).send().map_err(|e| e.to_string())?;
            response.error_for_status_ref().map_err(|e| e.to_string())?;
            let bytes = response.bytes().map_err(|e| e.to_string())?;
            // Validate before caching so a bad body is never stored.
            let heights = decode_tile(&bytes)?;
            std::fs::write(tile_path, &bytes).map_err(|e| e.to_string())?;
            Ok(heights)
        })();
        match result {
            Ok(h) => return Ok(h),
            Err(e) => last_error = e,
        }
    }
    Err(format!(
        "failed after {TILE_DOWNLOAD_MAX_RETRIES} attempts: {last_error}"
    ))
}

fn calculate_zoom_level(bbox: &LLBBox) -> u8 {
    let lat_diff = (bbox.max().lat() - bbox.min().lat()).abs();
    let lng_diff = (bbox.max().lng() - bbox.min().lng()).abs();
    let max_diff = lat_diff.max(lng_diff);
    let zoom = (-max_diff.log2() + 20.0) as u8;
    let mut zoom = zoom.clamp(MIN_ZOOM, gsi_elevation::max_zoom());
    while zoom > MIN_ZOOM && tile_range(bbox, zoom).count() > MAX_TILES_PER_FETCH {
        zoom -= 1;
    }
    zoom
}

struct TileRange {
    x: (u32, u32),
    y: (u32, u32),
}

impl TileRange {
    fn count(&self) -> usize {
        (self.x.1 - self.x.0 + 1) as usize * (self.y.1 - self.y.0 + 1) as usize
    }
}

fn tile_range(bbox: &LLBBox, zoom: u8) -> TileRange {
    let (x1, y1) = lat_lng_to_tile(bbox.min().lat(), bbox.min().lng(), zoom);
    let (x2, y2) = lat_lng_to_tile(bbox.max().lat(), bbox.max().lng(), zoom);
    TileRange {
        x: (x1.min(x2), x1.max(x2)),
        y: (y1.min(y2), y1.max(y2)),
    }
}

fn get_tile_coordinates(bbox: &LLBBox, zoom: u8) -> Vec<(u32, u32)> {
    let r = tile_range(bbox, zoom);
    let mut tiles = Vec::new();
    for x in r.x.0..=r.x.1 {
        for y in r.y.0..=r.y.1 {
            tiles.push((x, y));
        }
    }
    tiles
}

fn lat_lng_to_tile(lat: f64, lng: f64, zoom: u8) -> (u32, u32) {
    let n = 2.0_f64.powi(zoom as i32);
    let n_tiles = n as i64;
    let x = (((lng + 180.0) / 360.0 * n).floor() as i64).clamp(0, n_tiles - 1) as u32;
    let y = (((1.0 - lat.to_radians().tan().asinh() / std::f64::consts::PI) / 2.0 * n).floor()
        as i64)
        .clamp(0, n_tiles - 1) as u32;
    (x, y)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zoom_is_capped_at_gsi_max() {
        let bbox = LLBBox::new(34.5825, 135.5150, 34.5840, 135.5175).unwrap();
        assert!(calculate_zoom_level(&bbox) <= gsi_elevation::max_zoom());
    }

    #[test]
    fn missing_tile_samples_as_nan() {
        let map: HashMap<(u32, u32), TileHeights> = HashMap::new();
        assert!(sample(&map, 1, 1, 0, 0).is_nan());
    }

    #[test]
    fn sample_crosses_tile_boundary() {
        let mut map: HashMap<(u32, u32), TileHeights> = HashMap::new();
        let mut right = vec![f64::NAN; TILE_SIZE * TILE_SIZE];
        right[0] = 42.0;
        map.insert((6, 5), right);
        assert_eq!(sample(&map, 5, 5, TILE_SIZE as i32, 0), 42.0);
    }
}
