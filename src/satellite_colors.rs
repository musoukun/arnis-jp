//! Satellite image color extraction for building wall colors.
//!
//! Downloads satellite tiles for the world's bounding box (or uses a provided image),
//! samples colors at each building's footprint, and injects `building:colour` tags.
//! The existing `determine_wall_block` logic then picks a matching Minecraft block.

use crate::coordinate_system::cartesian::XZBBox;
use crate::coordinate_system::geographic::LLBBox;
use crate::osm_parser::ProcessedElement;
use image::{DynamicImage, GenericImageView, RgbImage};
use std::path::{Path, PathBuf};

/// ArcGIS World Imagery tile server (no API key required)
const SATELLITE_TILE_URL: &str =
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
/// Zoom level for satellite tiles (18 = ~0.6m/pixel, 2x world resolution)
const SATELLITE_ZOOM: u8 = 18;

/// Download satellite tiles for the given bounding box and stitch them into one image.
pub fn fetch_satellite_image(llbbox: &LLBBox) -> Result<DynamicImage, String> {
    let zoom = SATELLITE_ZOOM;
    let n = 2f64.powi(zoom as i32);

    // Convert lat/lng to tile coordinates
    let x_min = ((llbbox.min().lng() + 180.0) / 360.0 * n).floor() as u32;
    let x_max = ((llbbox.max().lng() + 180.0) / 360.0 * n).floor() as u32;

    let y_min = ((1.0 - (llbbox.max().lat().to_radians().tan()
        + 1.0 / llbbox.max().lat().to_radians().cos())
    .ln()
        / std::f64::consts::PI)
        / 2.0
        * n)
        .floor() as u32;
    let y_max = ((1.0 - (llbbox.min().lat().to_radians().tan()
        + 1.0 / llbbox.min().lat().to_radians().cos())
    .ln()
        / std::f64::consts::PI)
        / 2.0
        * n)
        .floor() as u32;

    let tiles_x = x_max - x_min + 1;
    let tiles_y = y_max - y_min + 1;
    let total_tiles = tiles_x * tiles_y;

    println!(
        "Fetching {} satellite tiles (zoom={}, {}x{})...",
        total_tiles, zoom, tiles_x, tiles_y
    );

    // Download tiles
    let tile_size: u32 = 256;
    let mut stitched = RgbImage::new(tiles_x * tile_size, tiles_y * tile_size);

    let cache_dir = PathBuf::from("./arnis-tile-cache");
    if !cache_dir.exists() {
        std::fs::create_dir_all(&cache_dir)
            .map_err(|e| format!("Failed to create tile cache dir: {e}"))?;
    }

    for ty in y_min..=y_max {
        for tx in x_min..=x_max {
            let cache_path = cache_dir.join(format!("sat_z{}_x{}_y{}.jpg", zoom, tx, ty));

            let tile_img = if cache_path.exists() {
                image::open(&cache_path)
                    .map_err(|e| format!("Failed to read cached tile: {e}"))?
                    .to_rgb8()
            } else {
                let url = SATELLITE_TILE_URL
                    .replace("{z}", &zoom.to_string())
                    .replace("{x}", &tx.to_string())
                    .replace("{y}", &ty.to_string());

                let body = reqwest::blocking::get(&url)
                    .map_err(|e| format!("Failed to download satellite tile: {e}"))?
                    .bytes()
                    .map_err(|e| format!("Failed to read tile body: {e}"))?;

                let tile = image::load_from_memory(&body)
                    .map_err(|e| format!("Failed to decode satellite tile: {e}"))?
                    .to_rgb8();

                // Cache it
                if let Err(e) = tile.save(&cache_path) {
                    eprintln!("Warning: Failed to cache satellite tile: {e}");
                }

                tile
            };

            // Copy tile into stitched image
            let offset_x = (tx - x_min) * tile_size;
            let offset_y = (ty - y_min) * tile_size;
            for py in 0..tile_size.min(tile_img.height()) {
                for px in 0..tile_size.min(tile_img.width()) {
                    let pixel = tile_img.get_pixel(px, py);
                    if offset_x + px < stitched.width() && offset_y + py < stitched.height() {
                        stitched.put_pixel(offset_x + px, offset_y + py, *pixel);
                    }
                }
            }
        }
    }

    println!(
        "Satellite image: {}x{} pixels",
        stitched.width(),
        stitched.height()
    );

    // Crop the stitched image to exactly match the bbox
    let tile_min_lng: f64 = (x_min as f64 / n) * 360.0 - 180.0;
    let tile_max_lng: f64 = ((x_max as f64 + 1.0) / n) * 360.0 - 180.0;
    let tile_max_lat: f64 = (std::f64::consts::PI * (1.0 - 2.0 * y_min as f64 / n))
        .sinh()
        .atan()
        .to_degrees();
    let tile_min_lat: f64 = (std::f64::consts::PI * (1.0 - 2.0 * (y_max as f64 + 1.0) / n))
        .sinh()
        .atan()
        .to_degrees();

    let full_w: f64 = stitched.width() as f64;
    let full_h: f64 = stitched.height() as f64;

    let lng_range = tile_max_lng - tile_min_lng;
    let lat_range = tile_max_lat - tile_min_lat;

    let crop_x = ((llbbox.min().lng() - tile_min_lng) / lng_range * full_w) as u32;
    let crop_y = ((tile_max_lat - llbbox.max().lat()) / lat_range * full_h) as u32;
    let crop_w = ((llbbox.max().lng() - llbbox.min().lng()) / lng_range * full_w) as u32;
    let crop_h = ((llbbox.max().lat() - llbbox.min().lat()) / lat_range * full_h) as u32;

    println!(
        "Crop: x={}, y={}, w={}, h={} (from {}x{})",
        crop_x, crop_y, crop_w, crop_h,
        stitched.width(), stitched.height()
    );

    let cropped = DynamicImage::ImageRgb8(stitched).crop_imm(
        crop_x.min(full_w as u32 - 1),
        crop_y.min(full_h as u32 - 1),
        crop_w.min(full_w as u32 - crop_x),
        crop_h.min(full_h as u32 - crop_y),
    );

    println!("Cropped satellite image: {}x{}", cropped.width(), cropped.height());

    Ok(cropped)
}

/// Download satellite tiles for the bbox and apply colors to building elements.
pub fn apply_satellite_colors(
    elements: &mut Vec<ProcessedElement>,
    xzbbox: &XZBBox,
    llbbox: &LLBBox,
) -> Result<usize, String> {
    let img = fetch_satellite_image(llbbox)?;

    // Save satellite image for debugging
    if let Err(e) = img.save("satellite_debug.png") {
        eprintln!("Warning: Failed to save debug satellite image: {e}");
    } else {
        println!("Saved satellite_debug.png for inspection");
    }

    let (img_w, img_h) = img.dimensions();
    let world_w = xzbbox.max_x() as f64;
    let world_h = xzbbox.max_z() as f64;

    if world_w <= 0.0 || world_h <= 0.0 {
        return Err("Invalid world bounding box".to_string());
    }

    println!(
        "Satellite color extraction: image {}x{}, world {}x{}",
        img_w, img_h, world_w as i32, world_h as i32
    );

    let mut colored_count = 0;

    // Helper: sample color from image at node positions
    let sample_color = |nodes: &[crate::osm_parser::ProcessedNode]| -> Option<String> {
        let mut r_sum: u64 = 0;
        let mut g_sum: u64 = 0;
        let mut b_sum: u64 = 0;
        let mut count: u64 = 0;

        for node in nodes {
            let px = ((node.x as f64 / world_w) * img_w as f64) as u32;
            let pz = ((node.z as f64 / world_h) * img_h as f64) as u32;

            if px < img_w && pz < img_h {
                let pixel = img.get_pixel(px, pz);
                r_sum += pixel[0] as u64;
                g_sum += pixel[1] as u64;
                b_sum += pixel[2] as u64;
                count += 1;
            }
        }

        if count > 0 {
            let avg_r = (r_sum / count) as u8;
            let avg_g = (g_sum / count) as u8;
            let avg_b = (b_sum / count) as u8;
            Some(format!("#{:02X}{:02X}{:02X}", avg_r, avg_g, avg_b))
        } else {
            None
        }
    };

    for element in elements.iter_mut() {
        match element {
            ProcessedElement::Way(ref mut way) => {
                let is_building = way.tags.contains_key("building")
                    || way.tags.contains_key("building:part");
                if !is_building || way.tags.contains_key("building:colour") {
                    continue;
                }

                if let Some(hex) = sample_color(&way.nodes) {
                    way.tags.insert("building:colour".to_string(), hex);
                    colored_count += 1;
                }
            }
            ProcessedElement::Relation(ref mut rel) => {
                let is_building = rel.tags.contains_key("building")
                    || rel.tags.contains_key("building:part")
                    || rel.tags.get("type").map(|t| t.as_str()) == Some("building");
                if !is_building || rel.tags.contains_key("building:colour") {
                    continue;
                }

                // Sample from all member way nodes
                let all_nodes: Vec<_> = rel.members
                    .iter()
                    .flat_map(|m| m.way.nodes.iter().cloned())
                    .collect();

                if let Some(hex) = sample_color(&all_nodes) {
                    // Set on the relation — this propagates to synthetic ways
                    // via relation.tags.clone() in generate_building_from_relation
                    rel.tags.insert("building:colour".to_string(), hex);
                    colored_count += 1;
                }
            }
            _ => {}
        }
    }

    println!("Applied satellite colors to {} buildings", colored_count);
    Ok(colored_count)
}
