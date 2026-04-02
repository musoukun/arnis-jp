/// GSI (国土地理院) DEM tile handling.
///
/// This module isolates Japan-specific elevation tile logic
/// (URL, zoom, pixel decoding, no-data detection) so that
/// `elevation_data.rs` stays close to upstream and merge
/// conflicts are minimised.

/// GSI DEM PNG tiles endpoint (no API key required, Japan only)
pub const GSI_DEM_URL: &str =
    "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png";

/// Maximum zoom level for GSI DEM tiles
pub const GSI_MAX_ZOOM: u8 = 14;

/// Source display name for log messages.
pub fn source_name() -> &'static str {
    "GSI DEM"
}

/// URL template for GSI DEM tiles.
pub fn tile_url() -> &'static str {
    GSI_DEM_URL
}

/// Maximum zoom level.
pub fn max_zoom() -> u8 {
    GSI_MAX_ZOOM
}

/// Cache file prefix for GSI tiles (distinguishes from Terrarium "z" prefix).
pub fn cache_prefix() -> &'static str {
    "gsi"
}

/// Returns `true` if the GSI DEM pixel represents no-data (alpha == 0).
pub fn is_nodata(alpha: u8) -> bool {
    alpha == 0
}

/// Decode a GSI DEM PNG pixel to height in metres.
///
/// GSI DEM PNG encodes elevation as a 24-bit signed integer:
///   raw = R * 65536 + G * 256 + B
///   if raw >= 2^23 then raw -= 2^24   (two's complement)
///   height = raw * 0.01
pub fn decode_pixel(r: u8, g: u8, b: u8) -> f64 {
    let raw = r as i64 * 65536 + g as i64 * 256 + b as i64;
    let signed = if raw >= 8_388_608 {
        raw - 16_777_216
    } else {
        raw
    };
    signed as f64 * 0.01
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_positive_height() {
        // 100.00m = 10000 => R=0, G=39, B=16
        let h = decode_pixel(0, 39, 16);
        assert!((h - 100.0).abs() < 0.02);
    }

    #[test]
    fn decode_zero_height() {
        let h = decode_pixel(0, 0, 0);
        assert!((h - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn decode_negative_height() {
        // -1.00m = -100 => two's complement: 16777116 => R=255, G=255, B=156
        let raw: i64 = 16_777_216 - 100;
        let r = ((raw >> 16) & 0xFF) as u8;
        let g = ((raw >> 8) & 0xFF) as u8;
        let b = (raw & 0xFF) as u8;
        let h = decode_pixel(r, g, b);
        assert!((h - (-1.0)).abs() < 0.02);
    }

    #[test]
    fn nodata_detection() {
        assert!(is_nodata(0));
        assert!(!is_nodata(255));
    }
}
