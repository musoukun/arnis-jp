//! GSI 3D (国土地理院 電子国土基本図 3次元データ) GML parser.
//!
//! Reads `BldA3d` elements from a GML file produced by GSI and exposes them
//! through the [`HeightProvider`] trait so the building pipeline can query
//! heights by centroid coordinate.
//!
//! # GML structure (relevant parts)
//!
//! ```xml
//! <dkgd3d:BldA3d gml:id="...">
//!   <dkgd:ftCode>3101</dkgd:ftCode>
//!   <dkgd:area>
//!     <gml:Surface ...>
//!       <gml:posList>lat lng lat lng ...</gml:posList>
//!     </gml:Surface>
//!   </dkgd:area>
//!   <dkgd3d:maxElv>19.58</dkgd3d:maxElv>
//!   <dkgd3d:grElv>14.77</dkgd3d:grElv>
//! </dkgd3d:BldA3d>
//! ```
//!
//! Building height = `maxElv - grElv`.

use super::{HeightProvider, HeightResult};
use std::io::BufReader;
use std::path::Path;

/// Maximum distance (in degrees) between centroids to consider a match.
/// ~30 m at mid-latitudes (≈ 0.00027°).
const MATCH_THRESHOLD_DEG: f64 = 0.0003;

/// Squared threshold for fast distance comparison (avoids sqrt).
const MATCH_THRESHOLD_SQ: f64 = MATCH_THRESHOLD_DEG * MATCH_THRESHOLD_DEG;

/// A single building parsed from the GML file.
#[derive(Debug, Clone)]
pub struct Gsi3dBuilding {
    /// Centroid latitude.
    pub centroid_lat: f64,
    /// Centroid longitude.
    pub centroid_lng: f64,
    /// Building height in metres (`maxElv - grElv`).
    pub height_m: f64,
    /// Ground elevation in metres.
    pub ground_elv: f64,
    /// Feature type code (3101=普通建物, 3102=堅ろう建物, 3111=無壁舎).
    pub ft_code: u32,
}

/// Height provider backed by a pre-parsed list of GSI 3D buildings.
///
/// Buildings are stored in a flat `Vec` and searched linearly. For the
/// typical case (~11 000 buildings per mesh) this is fast enough because
/// the vector fits in L2/L3 cache and the comparison is a simple f64
/// distance check.
pub struct Gsi3dProvider {
    buildings: Vec<Gsi3dBuilding>,
}

impl Gsi3dProvider {
    /// Parse a GML file and return a provider ready for lookups.
    pub fn from_gml_file(path: &Path) -> Result<Self, String> {
        let buildings = parse_gml(path)?;
        println!(
            "[GSI-3D] Loaded {} buildings from {}",
            buildings.len(),
            path.display()
        );
        Ok(Self { buildings })
    }

    /// Number of buildings loaded.
    pub fn building_count(&self) -> usize {
        self.buildings.len()
    }
}

impl HeightProvider for Gsi3dProvider {
    fn lookup(&self, lat: f64, lng: f64) -> Option<HeightResult> {
        let mut best: Option<(f64, &Gsi3dBuilding)> = None;

        for bld in &self.buildings {
            let dlat = bld.centroid_lat - lat;
            let dlng = bld.centroid_lng - lng;
            let dist_sq = dlat * dlat + dlng * dlng;

            if dist_sq > MATCH_THRESHOLD_SQ {
                continue;
            }

            match best {
                Some((best_dist, _)) if dist_sq < best_dist => {
                    best = Some((dist_sq, bld));
                }
                None => {
                    best = Some((dist_sq, bld));
                }
                _ => {}
            }
        }

        best.map(|(_, bld)| HeightResult {
            height_m: bld.height_m,
            ground_elv_m: Some(bld.ground_elv),
            source: "GSI-3D",
        })
    }

    fn name(&self) -> &'static str {
        "GSI-3D"
    }
}

// ---------------------------------------------------------------------------
// GML Parsing (streaming with quick-xml)
// ---------------------------------------------------------------------------

/// XML element names we care about (local names, ignoring namespace prefixes).
const TAG_BLD_A3D: &[u8] = b"BldA3d";
const TAG_FT_CODE: &[u8] = b"ftCode";
const TAG_POS_LIST: &[u8] = b"posList";
const TAG_MAX_ELV: &[u8] = b"maxElv";
const TAG_GR_ELV: &[u8] = b"grElv";

/// Parse a GML file into a list of [`Gsi3dBuilding`].
fn parse_gml(path: &Path) -> Result<Vec<Gsi3dBuilding>, String> {
    use quick_xml::events::Event;
    use quick_xml::reader::Reader;

    let file = std::fs::File::open(path)
        .map_err(|e| format!("Failed to open GML file {}: {}", path.display(), e))?;
    let buf_reader = BufReader::with_capacity(256 * 1024, file);
    let mut reader = Reader::from_reader(buf_reader);
    reader.config_mut().trim_text(true);

    let mut buildings: Vec<Gsi3dBuilding> = Vec::new();
    let mut buf = Vec::with_capacity(4096);

    // State for the current <BldA3d> element being parsed.
    let mut in_bld = false;
    let mut current_tag = CurrentTag::None;
    let mut ft_code: u32 = 0;
    let mut pos_list_text = String::new();
    let mut max_elv: f64 = 0.0;
    let mut gr_elv: f64 = 0.0;

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(ref e)) | Ok(Event::Empty(ref e)) => {
                let name = e.name();
                let local = local_name(name.as_ref());
                if local == TAG_BLD_A3D {
                    in_bld = true;
                    ft_code = 0;
                    pos_list_text.clear();
                    max_elv = 0.0;
                    gr_elv = 0.0;
                } else if in_bld {
                    current_tag = match local {
                        x if x == TAG_FT_CODE => CurrentTag::FtCode,
                        x if x == TAG_POS_LIST => CurrentTag::PosList,
                        x if x == TAG_MAX_ELV => CurrentTag::MaxElv,
                        x if x == TAG_GR_ELV => CurrentTag::GrElv,
                        _ => CurrentTag::None,
                    };
                }
            }
            Ok(Event::Text(ref e)) if in_bld => {
                let text = e
                    .unescape()
                    .map_err(|err| format!("XML text decode error: {err}"))?;
                match current_tag {
                    CurrentTag::FtCode => {
                        ft_code = text.trim().parse::<u32>().unwrap_or(0);
                    }
                    CurrentTag::PosList => {
                        pos_list_text.push_str(text.as_ref());
                    }
                    CurrentTag::MaxElv => {
                        max_elv = text.trim().parse::<f64>().unwrap_or(0.0);
                    }
                    CurrentTag::GrElv => {
                        gr_elv = text.trim().parse::<f64>().unwrap_or(0.0);
                    }
                    CurrentTag::None => {}
                }
            }
            Ok(Event::End(ref e)) => {
                let name = e.name();
                let local = local_name(name.as_ref());
                if local == TAG_BLD_A3D && in_bld {
                    // Finalise building
                    let height_m = max_elv - gr_elv;
                    if height_m > 0.0 && !pos_list_text.is_empty() {
                        if let Some((clat, clng)) = centroid_from_pos_list(&pos_list_text) {
                            buildings.push(Gsi3dBuilding {
                                centroid_lat: clat,
                                centroid_lng: clng,
                                height_m,
                                ground_elv: gr_elv,
                                ft_code,
                            });
                        }
                    }
                    in_bld = false;
                }
                current_tag = CurrentTag::None;
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(format!("XML parse error at position {}: {e}", reader.error_position())),
            _ => {}
        }
        buf.clear();
    }

    Ok(buildings)
}

/// Which text content we're currently collecting.
#[derive(Debug, Clone, Copy, PartialEq)]
enum CurrentTag {
    None,
    FtCode,
    PosList,
    MaxElv,
    GrElv,
}

/// Extract the local name from a potentially namespaced XML tag.
/// e.g. `dkgd3d:BldA3d` → `BldA3d`, `gml:posList` → `posList`.
fn local_name(full: &[u8]) -> &[u8] {
    match full.iter().position(|&b| b == b':') {
        Some(pos) => &full[pos + 1..],
        None => full,
    }
}

/// Compute the centroid of a `posList` string.
///
/// The format is `lat lng lat lng ...` (space-separated, lat-lng pairs).
/// The last point may duplicate the first (closed polygon); we skip it.
fn centroid_from_pos_list(text: &str) -> Option<(f64, f64)> {
    let values: Vec<f64> = text
        .split_whitespace()
        .filter_map(|s| s.parse::<f64>().ok())
        .collect();

    // Need at least 3 coordinate pairs (6 values) for a polygon.
    if values.len() < 6 || values.len() % 2 != 0 {
        return None;
    }

    let pair_count = values.len() / 2;

    // Skip the closing point if it duplicates the first.
    let n = if pair_count > 1
        && (values[0] - values[values.len() - 2]).abs() < 1e-10
        && (values[1] - values[values.len() - 1]).abs() < 1e-10
    {
        pair_count - 1
    } else {
        pair_count
    };

    if n == 0 {
        return None;
    }

    let mut sum_lat = 0.0;
    let mut sum_lng = 0.0;
    for i in 0..n {
        sum_lat += values[i * 2];
        sum_lng += values[i * 2 + 1];
    }

    Some((sum_lat / n as f64, sum_lng / n as f64))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_centroid_simple_square() {
        // Pairs: (lat=0, lng=0), (lat=0, lng=1), (lat=1, lng=1), (lat=1, lng=0), close
        let pos = "0.0 0.0 0.0 1.0 1.0 1.0 1.0 0.0 0.0 0.0";
        let (lat, lng) = centroid_from_pos_list(pos).unwrap();
        assert!((lat - 0.5).abs() < 1e-9);
        assert!((lng - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_centroid_too_few_points() {
        assert!(centroid_from_pos_list("1.0 2.0").is_none());
        assert!(centroid_from_pos_list("1.0 2.0 3.0 4.0").is_none());
    }

    #[test]
    fn test_local_name_with_namespace() {
        assert_eq!(local_name(b"dkgd3d:BldA3d"), b"BldA3d");
        assert_eq!(local_name(b"gml:posList"), b"posList");
        assert_eq!(local_name(b"ftCode"), b"ftCode");
    }

    #[test]
    fn test_match_threshold() {
        // 0.0003 degrees ≈ 33m at equator, which is reasonable for building matching
        assert!(MATCH_THRESHOLD_SQ > 0.0);
        assert!(MATCH_THRESHOLD_SQ < 0.001);
    }

    #[test]
    fn test_provider_lookup() {
        let provider = Gsi3dProvider {
            buildings: vec![
                Gsi3dBuilding {
                    centroid_lat: 35.0,
                    centroid_lng: 139.0,
                    height_m: 15.0,
                    ground_elv: 5.0,
                    ft_code: 3101,
                },
                Gsi3dBuilding {
                    centroid_lat: 35.001,
                    centroid_lng: 139.001,
                    height_m: 30.0,
                    ground_elv: 3.0,
                    ft_code: 3102,
                },
            ],
        };

        // Exact match on first building
        let result = provider.lookup(35.0, 139.0).unwrap();
        assert!((result.height_m - 15.0).abs() < f64::EPSILON);

        // Too far from any building
        assert!(provider.lookup(36.0, 140.0).is_none());

        // Close to second building
        let result = provider.lookup(35.0010001, 139.0010001).unwrap();
        assert!((result.height_m - 30.0).abs() < f64::EPSILON);
    }
}
