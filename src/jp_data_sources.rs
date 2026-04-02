/// Japan-specific data source orchestration.
///
/// Consolidates GSI building merge, satellite color application,
/// and Japan-specific height providers (GSI-3D, PLATEAU) into
/// thin wrapper functions.  `main.rs` and `gui.rs` call these
/// one-liners instead of inlining the logic, keeping upstream
/// merge diffs minimal.

use colored::Colorize;

use crate::args::Args;
use crate::building_height::HeightResolver;
use crate::coordinate_system::cartesian::XZBBox;
use crate::coordinate_system::geographic::LLBBox;
use crate::osm_parser::{OsmData, ProcessedElement};

/// Merge GSI building vector tile data into raw OSM data.
///
/// No-op when `args.gsi` is false.
pub fn merge_gsi_buildings_if_enabled(args: &Args, raw_data: &mut OsmData) {
    if !args.gsi {
        return;
    }
    println!(
        "{} Fetching GSI building data...",
        "[GSI]".bright_white().bold()
    );
    match crate::gsi_data::fetch_gsi_buildings(args.bbox) {
        Ok(gsi_data) => {
            raw_data.merge(gsi_data);
        }
        Err(e) => {
            eprintln!(
                "{} Failed to fetch GSI data: {}",
                "Warning:".yellow().bold(),
                e
            );
        }
    }
}

/// Apply satellite-based building wall colours.
///
/// No-op when `args.satellite` is false.
pub fn apply_satellite_colors_if_enabled(
    args: &Args,
    parsed_elements: &mut Vec<ProcessedElement>,
    xzbbox: &XZBBox,
) {
    if !args.satellite {
        return;
    }
    match crate::satellite_colors::apply_satellite_colors(parsed_elements, xzbbox, &args.bbox) {
        Ok(count) => println!("Applied satellite colors to {count} buildings"),
        Err(e) => eprintln!(
            "{} Failed to apply satellite colors: {}",
            "Warning:".yellow().bold(),
            e
        ),
    }
}

/// Register Japan-specific height data providers on the resolver.
///
/// Currently supports:
/// - GSI 3D GML (`--gsi-3d <FILE>`, highest priority)
/// - PLATEAU 3D Tiles (`--plateau`)
///
/// No-op when neither flag is set.
pub fn add_jp_height_providers(args: &Args, height_resolver: &mut HeightResolver) {
    // GSI 3D (highest priority)
    if let Some(ref gml_path) = args.gsi_3d {
        println!(
            "{} Loading GSI 3D building height data...",
            "[GSI-3D]".bright_white().bold()
        );
        match crate::building_height::gsi_3d::Gsi3dProvider::from_gml_file(
            std::path::Path::new(gml_path),
        ) {
            Ok(provider) => {
                height_resolver.add_provider(Box::new(provider));
            }
            Err(e) => {
                eprintln!(
                    "{} Failed to load GSI 3D data: {}",
                    "Warning:".yellow().bold(),
                    e
                );
            }
        }
    }

    // PLATEAU
    if args.plateau {
        println!(
            "{} Fetching PLATEAU building height data...",
            "[PLATEAU]".bright_white().bold()
        );
        match crate::building_height::plateau::PlateauProvider::from_bbox(
            args.bbox.min().lat(),
            args.bbox.min().lng(),
            args.bbox.max().lat(),
            args.bbox.max().lng(),
        ) {
            Ok(provider) => {
                height_resolver.add_provider(Box::new(provider));
            }
            Err(e) => {
                eprintln!(
                    "{} PLATEAU data unavailable: {}",
                    "Warning:".yellow().bold(),
                    e
                );
            }
        }
    }
}
