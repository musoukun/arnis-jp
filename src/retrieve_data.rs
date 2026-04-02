use crate::coordinate_system::geographic::LLBBox;
use crate::osm_parser::OsmData;
use crate::progress::{emit_gui_error, emit_gui_progress_update, is_running_with_gui};
#[cfg(feature = "gui")]
use crate::telemetry::{send_log, LogLevel};
use colored::Colorize;
use rand::prelude::IndexedRandom;
use reqwest::blocking::Client;
use reqwest::blocking::ClientBuilder;
use serde::Deserialize;
use serde_json::Value;
use std::fs::File;
use std::io::{self, BufReader, Cursor, Write};
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

/// Returns the OSM data cache directory path.
fn get_osm_cache_dir() -> PathBuf {
    if let Some(cache_dir) = dirs::cache_dir() {
        cache_dir.join("arnis").join("osm_cache")
    } else {
        PathBuf::from("./arnis-osm-cache")
    }
}

/// Generates a cache filename from bbox coordinates.
fn bbox_cache_filename(bbox: &LLBBox) -> String {
    format!(
        "osm_{:.6}_{:.6}_{:.6}_{:.6}.json",
        bbox.min().lat(),
        bbox.min().lng(),
        bbox.max().lat(),
        bbox.max().lng(),
    )
}

/// Saves OSM data to the auto-cache directory.
fn save_to_auto_cache(bbox: &LLBBox, data: &str) {
    let cache_dir = get_osm_cache_dir();
    if std::fs::create_dir_all(&cache_dir).is_err() {
        return;
    }
    let cache_path = cache_dir.join(bbox_cache_filename(bbox));
    if let Ok(mut file) = File::create(&cache_path) {
        let _ = file.write_all(data.as_bytes());
        println!(
            "OSM data cached to: {}",
            cache_path.display().to_string().bright_black()
        );
    }
}

/// Attempts to load OSM data from the auto-cache directory.
fn load_from_auto_cache(bbox: &LLBBox) -> Option<OsmData> {
    let cache_path = get_osm_cache_dir().join(bbox_cache_filename(bbox));
    if !cache_path.exists() {
        return None;
    }
    let file = File::open(&cache_path).ok()?;
    let reader = BufReader::new(file);
    let mut deserializer = serde_json::Deserializer::from_reader(reader);
    let data = OsmData::deserialize(&mut deserializer).ok()?;
    Some(data)
}

/// Function to download data using reqwest
fn download_with_reqwest(url: &str, query: &str) -> Result<String, Box<dyn std::error::Error>> {
    let client: Client = ClientBuilder::new()
        .timeout(Duration::from_secs(360))
        .user_agent(concat!("arnis/", env!("CARGO_PKG_VERSION")))
        .build()?;

    let response: Result<reqwest::blocking::Response, reqwest::Error> =
        client.get(url).query(&[("data", query)]).send();

    match response {
        Ok(resp) => {
            emit_gui_progress_update(3.0, "OSMデータをダウンロード中... / Downloading data...");
            if resp.status().is_success() {
                let text = resp.text()?;
                if text.is_empty() {
                    return Err("Received invalid data from server".into());
                }
                Ok(text)
            } else {
                let status = resp.status();
                let user_msg = match status.as_u16() {
                    429 => "Rate limited. Try again later.".to_string(),
                    403 => "Server overloaded. Try again.".to_string(),
                    500 | 502 | 503 | 504 => "Server unavailable. Try again.".to_string(),
                    _ => format!("Response code: {}", status.as_u16()),
                };
                eprintln!("{}", format!("Error! {user_msg}").red().bold());
                Err(user_msg.into())
            }
        }
        Err(e) => {
            if e.is_timeout() {
                let msg = "Request timed out. Try selecting a smaller area.";
                eprintln!("{}", format!("Error! {msg}").red().bold());
                Err(msg.into())
            } else if e.is_connect() {
                let msg = "No internet connection.";
                eprintln!("{}", format!("Error! {msg}").red().bold());
                Err(msg.into())
            } else {
                #[cfg(feature = "gui")]
                send_log(
                    LogLevel::Error,
                    &format!("Request error in download_with_reqwest: {e}"),
                );
                eprintln!("{}", format!("Error! {e:.52}").red().bold());
                Err(format!("{e:.52}").into())
            }
        }
    }
}

/// Function to download data using `curl`
fn download_with_curl(url: &str, query: &str) -> io::Result<String> {
    let output: std::process::Output = Command::new("curl")
        .arg("-s") // Add silent mode to suppress output
        .arg(format!("{url}?data={query}"))
        .output()?;

    if !output.status.success() {
        Err(io::Error::other("Curl command failed"))
    } else {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}

/// Function to download data using `wget`
fn download_with_wget(url: &str, query: &str) -> io::Result<String> {
    let output: std::process::Output = Command::new("wget")
        .arg("-qO-") // Use `-qO-` to output the result directly to stdout
        .arg(format!("{url}?data={query}"))
        .output()?;

    if !output.status.success() {
        Err(io::Error::other("Wget command failed"))
    } else {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}

pub fn fetch_data_from_file(file: &str) -> Result<OsmData, Box<dyn std::error::Error>> {
    println!("{} Loading data from file...", "[1/7]".bold());
    emit_gui_progress_update(1.0, "キャッシュファイルからデータを読み込み中... / Loading data from file...");

    let file: File = File::open(file)?;
    let reader: BufReader<File> = BufReader::new(file);
    let mut deserializer = serde_json::Deserializer::from_reader(reader);
    let data: OsmData = OsmData::deserialize(&mut deserializer)?;
    Ok(data)
}

/// Main function to fetch data
pub fn fetch_data_from_overpass(
    bbox: LLBBox,
    debug: bool,
    download_method: &str,
    save_file: Option<&str>,
) -> Result<OsmData, Box<dyn std::error::Error>> {
    println!("{} Fetching data...", "[1/7]".bold());
    emit_gui_progress_update(1.0, "OSMデータを取得中... / Fetching data...");

    // List of Overpass API servers
    let api_servers: Vec<&str> = vec![
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://z.overpass-api.de/api/interpreter",
    ];
    let fallback_api_servers: Vec<&str> = vec![
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ];
    let mut url: &&str = api_servers.choose(&mut rand::rng()).unwrap();

    // Generate Overpass API query for bounding box.
    // Ocean/coastal elements are excluded because ESA WorldCover satellite data
    // handles ocean detection more reliably at 10m resolution (LC_WATER class).
    // Inland water (lakes, rivers, ponds) is still fetched from OSM.
    let query: String = format!(
        r#"[out:json][timeout:360][bbox:{},{},{},{}];
    (
        nwr["building"];
        nwr["building:part"];
        nwr["highway"];
        nwr["landuse"]["landuse"!="salt_pond"];
        nwr["natural"]["natural"!="coastline"]["natural"!="bay"]["natural"!="strait"];
        nwr["leisure"];
        nwr["water"]["water"!="bay"]["water"!="ocean"]["water"!="sea"]["tidal"!="yes"];
        nwr["waterway"]["waterway"!="tidal_channel"];
        nwr["amenity"];
        nwr["tourism"];
        nwr["bridge"];
        nwr["railway"];
        nwr["roller_coaster"];
        nwr["barrier"];
        nwr["entrance"];
        nwr["door"];
        nwr["power"];
        nwr["historic"];
        nwr["emergency"];
        nwr["advertising"];
        nwr["man_made"];
        nwr["aeroway"];
        way["place"]["place"!~"^(ocean|sea|bay|strait|sound|fjord)$"];
        way;
    )->.relsinbbox;
    (
        way(r.relsinbbox);
    )->.waysinbbox;
    (
        node(w.waysinbbox);
        node(w.relsinbbox);
    )->.nodesinbbox;
    .relsinbbox out body;
    .waysinbbox out body;
    .nodesinbbox out skel qt;"#,
        bbox.min().lat(),
        bbox.min().lng(),
        bbox.max().lat(),
        bbox.max().lng(),
    );

    {
        // Fetch data from Overpass API
        let mut attempt = 0;
        let max_attempts = 1;
        let response: String = loop {
            println!("Downloading from {url} with method {download_method}...");
            let result = match download_method {
                "requests" => download_with_reqwest(url, &query),
                "curl" => download_with_curl(url, &query).map_err(|e| e.into()),
                "wget" => download_with_wget(url, &query).map_err(|e| e.into()),
                _ => download_with_reqwest(url, &query), // Default to requests
            };

            match result {
                Ok(response) => break response,
                Err(error) => {
                    if attempt >= max_attempts {
                        // All servers failed — try auto-cache fallback
                        if let Some(cached_data) = load_from_auto_cache(&bbox) {
                            let msg_en = "API unavailable — using cached OSM data for this area";
                            let msg_ja = "APIに接続できないため、キャッシュ済みのOSMデータを使用します";
                            println!(
                                "{} {msg_en}",
                                "[Cache]".bright_white().bold()
                            );
                            // Show bilingual message in GUI progress
                            emit_gui_progress_update(
                                3.0,
                                &format!("{msg_ja} / {msg_en}"),
                            );
                            return Ok(cached_data);
                        }
                        return Err(error);
                    }

                    if download_method != "requests" {
                        eprintln!("Request failed: {error}");
                    }
                    println!("Switching to fallback server...");
                    url = fallback_api_servers.choose(&mut rand::rng()).unwrap();
                    attempt += 1;
                }
            }
        };

        // Auto-cache OSM data for this bbox (always)
        save_to_auto_cache(&bbox, &response);
        emit_gui_progress_update(
            4.0,
            "OSMデータをキャッシュしました / OSM data cached",
        );

        // Also save to user-specified file if requested
        if let Some(save_file) = save_file {
            let mut file: File = File::create(save_file)?;
            file.write_all(response.as_bytes())?;
            println!("API response saved to: {save_file}");
        }

        let mut deserializer =
            serde_json::Deserializer::from_reader(Cursor::new(response.as_bytes()));
        let data: OsmData = OsmData::deserialize(&mut deserializer)?;

        if data.is_empty() {
            if let Some(remark) = data.remark.as_deref() {
                // Check if the remark mentions memory or other runtime errors
                if remark.contains("runtime error") && remark.contains("out of memory") {
                    eprintln!("{}", "Error! The query ran out of memory on the Overpass API server. Try using a smaller area.".red().bold());
                    emit_gui_error("範囲が広すぎます。小さい範囲を選択してください");
                } else {
                    // Handle other Overpass API errors if present in the remark field
                    eprintln!("{}", format!("Error! API returned: {remark}").red().bold());
                    emit_gui_error(&format!("API returned: {remark}"));
                }
            } else {
                // General case for when there are no elements and no specific remark
                eprintln!(
                    "{}",
                    "Error! API returned no data. Please try again!"
                        .red()
                        .bold()
                );
                emit_gui_error("APIからデータが返されませんでした。再試行してください");
            }

            if debug {
                println!("Additional debug information: {data:?}");
            }

            if !is_running_with_gui() {
                std::process::exit(1);
            } else {
                return Err("Data fetch failed".into());
            }
        }

        emit_gui_progress_update(5.0, "");

        Ok(data)
    }
}

/// Fetches a short area name using Nominatim for the given lat/lon
pub fn fetch_area_name(lat: f64, lon: f64) -> Result<Option<String>, Box<dyn std::error::Error>> {
    let client = Client::builder()
        .timeout(Duration::from_secs(20))
        .user_agent(concat!("arnis/", env!("CARGO_PKG_VERSION")))
        .build()?;

    let url = format!("https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&addressdetails=1");

    let resp = client.get(&url).send()?;

    if !resp.status().is_success() {
        return Ok(None);
    }

    let json: Value = resp.json()?;

    if let Some(address) = json.get("address") {
        let fields = ["city", "town", "village", "county", "borough", "suburb"];
        for field in fields.iter() {
            if let Some(name) = address.get(*field).and_then(|v| v.as_str()) {
                let mut name_str = name.to_string();

                // Remove "City of " prefix
                if name_str.to_lowercase().starts_with("city of ") {
                    name_str = name_str[name_str.find(" of ").unwrap() + 4..].to_string();
                }

                return Ok(Some(name_str));
            }
        }
    }

    Ok(None)
}
