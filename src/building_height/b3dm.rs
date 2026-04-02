//! 3D Tiles b3dm (Batched 3D Model) binary parser.
//!
//! Parses the b3dm header, Feature Table, and Batch Table to extract
//! per-building properties such as `bldg:measuredHeight`.
//! The glTF body is intentionally skipped — we only need metadata.
//!
//! # b3dm binary layout
//!
//! ```text
//! [0..4]   magic: "b3dm"
//! [4..8]   version: u32 LE
//! [8..12]  byteLength: u32 LE
//! [12..16] featureTableJSONByteLength: u32 LE
//! [16..20] featureTableBinaryByteLength: u32 LE
//! [20..24] batchTableJSONByteLength: u32 LE
//! [24..28] batchTableBinaryByteLength: u32 LE
//! [28..]   Feature Table JSON | FT Binary | Batch Table JSON | BT Binary | glTF
//! ```

use serde_json::Value;

const B3DM_HEADER_SIZE: usize = 28;
const B3DM_MAGIC: &[u8; 4] = b"b3dm";

/// Parsed building data from a single b3dm tile.
#[derive(Debug, Clone)]
pub struct B3dmBuilding {
    /// Measured height in metres (from `bldg:measuredHeight`).
    pub measured_height: f64,
    /// Index within the tile (for debugging).
    pub index: usize,
}

/// Parse a b3dm binary blob and extract building heights.
///
/// Returns a list of buildings with their `measuredHeight`.
/// Buildings without a valid height are silently skipped.
pub fn parse_b3dm_heights(data: &[u8]) -> Result<Vec<B3dmBuilding>, String> {
    if data.len() < B3DM_HEADER_SIZE {
        return Err("b3dm data too short for header".into());
    }

    // Validate magic
    if &data[0..4] != B3DM_MAGIC {
        return Err(format!(
            "Invalid b3dm magic: expected 'b3dm', got {:?}",
            &data[0..4]
        ));
    }

    // Parse header
    let ft_json_len = read_u32_le(data, 12) as usize;
    let ft_bin_len = read_u32_le(data, 16) as usize;
    let bt_json_len = read_u32_le(data, 20) as usize;
    let bt_bin_len = read_u32_le(data, 24) as usize;

    // Section offsets
    let ft_json_start = B3DM_HEADER_SIZE;
    let ft_json_end = ft_json_start + ft_json_len;
    let bt_json_start = ft_json_end + ft_bin_len;
    let bt_json_end = bt_json_start + bt_json_len;
    let bt_bin_start = bt_json_end;
    let bt_bin_end = bt_bin_start + bt_bin_len;

    if bt_bin_end > data.len() {
        return Err(format!(
            "b3dm sections exceed data length: {} > {}",
            bt_bin_end,
            data.len()
        ));
    }

    // Parse Feature Table JSON to get BATCH_LENGTH
    let batch_length = if ft_json_len > 0 {
        let ft_json: Value = serde_json::from_slice(&data[ft_json_start..ft_json_end])
            .map_err(|e| format!("Feature Table JSON parse error: {e}"))?;
        ft_json
            .get("BATCH_LENGTH")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize
    } else {
        0
    };

    if batch_length == 0 || bt_json_len == 0 {
        return Ok(Vec::new());
    }

    // Parse Batch Table JSON
    let bt_json: Value = serde_json::from_slice(&data[bt_json_start..bt_json_end])
        .map_err(|e| format!("Batch Table JSON parse error: {e}"))?;

    let bt_binary = &data[bt_bin_start..bt_bin_end];

    // Extract measuredHeight for each building
    let heights = extract_measured_heights(&bt_json, bt_binary, batch_length);

    Ok(heights
        .into_iter()
        .enumerate()
        .filter_map(|(i, h)| {
            h.map(|measured_height| B3dmBuilding {
                measured_height,
                index: i,
            })
        })
        .collect())
}

/// Extract `bldg:measuredHeight` values from the Batch Table.
///
/// Handles two storage formats:
/// 1. **Binary**: JSON has `{ "byteOffset": N, "componentType": "DOUBLE", "type": "SCALAR" }`
///    and actual values are in the binary section.
/// 2. **Inline JSON array**: JSON has `"bldg:measuredHeight": [1.5, 2.3, ...]`
fn extract_measured_heights(
    bt_json: &Value,
    bt_binary: &[u8],
    batch_length: usize,
) -> Vec<Option<f64>> {
    let key = "bldg:measuredHeight";
    let mut heights = vec![None; batch_length];

    if let Some(prop) = bt_json.get(key) {
        if let Some(arr) = prop.as_array() {
            // Inline JSON array
            for (i, val) in arr.iter().enumerate().take(batch_length) {
                heights[i] = val.as_f64();
            }
        } else if prop.is_object() {
            // Binary reference
            read_binary_doubles(prop, bt_binary, batch_length, &mut heights);
        }
    }

    // Fallback: try "attributes" array (nested per-building objects)
    if heights.iter().all(|h| h.is_none()) {
        if let Some(attrs) = bt_json.get("attributes").and_then(|v| v.as_array()) {
            for (i, attr) in attrs.iter().enumerate().take(batch_length) {
                if let Some(h) = attr.get(key).and_then(|v| v.as_f64()) {
                    heights[i] = Some(h);
                }
            }
        }
    }

    heights
}

/// Read DOUBLE (f64) values from Batch Table binary.
fn read_binary_doubles(
    prop_def: &Value,
    binary: &[u8],
    count: usize,
    out: &mut [Option<f64>],
) {
    let byte_offset = prop_def
        .get("byteOffset")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as usize;

    let component_type = prop_def
        .get("componentType")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let bytes_per_element = match component_type {
        "DOUBLE" => 8,
        "FLOAT" => 4,
        _ => return, // Unsupported type
    };

    let required_len = byte_offset + count * bytes_per_element;
    if required_len > binary.len() {
        return;
    }

    for i in 0..count {
        let offset = byte_offset + i * bytes_per_element;
        let value = match component_type {
            "DOUBLE" => read_f64_le(binary, offset),
            "FLOAT" => read_f32_le(binary, offset) as f64,
            _ => continue,
        };
        if value.is_finite() && value >= 0.0 {
            out[i] = Some(value);
        }
    }
}

#[inline]
fn read_u32_le(data: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ])
}

#[inline]
fn read_f64_le(data: &[u8], offset: usize) -> f64 {
    let bytes: [u8; 8] = data[offset..offset + 8].try_into().unwrap();
    f64::from_le_bytes(bytes)
}

#[inline]
fn read_f32_le(data: &[u8], offset: usize) -> f32 {
    let bytes: [u8; 4] = data[offset..offset + 4].try_into().unwrap();
    f32::from_le_bytes(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a minimal valid b3dm blob for testing.
    fn make_test_b3dm(ft_json: &[u8], bt_json: &[u8], bt_binary: &[u8]) -> Vec<u8> {
        let ft_json_len = ft_json.len() as u32;
        let bt_json_len = bt_json.len() as u32;
        let bt_bin_len = bt_binary.len() as u32;
        let total = B3DM_HEADER_SIZE as u32 + ft_json_len + bt_json_len + bt_bin_len;

        let mut buf = Vec::with_capacity(total as usize);
        buf.extend_from_slice(b"b3dm"); // magic
        buf.extend_from_slice(&1u32.to_le_bytes()); // version
        buf.extend_from_slice(&total.to_le_bytes()); // byteLength
        buf.extend_from_slice(&ft_json_len.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes()); // ft binary len
        buf.extend_from_slice(&bt_json_len.to_le_bytes());
        buf.extend_from_slice(&bt_bin_len.to_le_bytes());
        buf.extend_from_slice(ft_json);
        buf.extend_from_slice(bt_json);
        buf.extend_from_slice(bt_binary);
        buf
    }

    #[test]
    fn test_parse_inline_heights() {
        let ft = br#"{"BATCH_LENGTH":3}"#;
        let bt = br#"{"bldg:measuredHeight":[10.5,20.0,5.2]}"#;
        let data = make_test_b3dm(ft, bt, &[]);

        let buildings = parse_b3dm_heights(&data).unwrap();
        assert_eq!(buildings.len(), 3);
        assert!((buildings[0].measured_height - 10.5).abs() < f64::EPSILON);
        assert!((buildings[1].measured_height - 20.0).abs() < f64::EPSILON);
        assert!((buildings[2].measured_height - 5.2).abs() < f64::EPSILON);
    }

    #[test]
    fn test_parse_binary_heights() {
        let ft = br#"{"BATCH_LENGTH":2}"#;
        let bt = br#"{"bldg:measuredHeight":{"byteOffset":0,"componentType":"DOUBLE","type":"SCALAR"}}"#;

        let mut binary = Vec::new();
        binary.extend_from_slice(&15.5f64.to_le_bytes());
        binary.extend_from_slice(&30.0f64.to_le_bytes());

        let data = make_test_b3dm(ft, bt, &binary);
        let buildings = parse_b3dm_heights(&data).unwrap();
        assert_eq!(buildings.len(), 2);
        assert!((buildings[0].measured_height - 15.5).abs() < f64::EPSILON);
        assert!((buildings[1].measured_height - 30.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_invalid_magic() {
        let data = b"not_b3dm_data_here_at_all!!!";
        assert!(parse_b3dm_heights(data).is_err());
    }

    #[test]
    fn test_empty_batch() {
        let ft = br#"{"BATCH_LENGTH":0}"#;
        let data = make_test_b3dm(ft, b"{}", &[]);
        let buildings = parse_b3dm_heights(&data).unwrap();
        assert!(buildings.is_empty());
    }
}
