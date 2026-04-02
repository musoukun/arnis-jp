//! Building height resolution from external data sources.
//!
//! This module provides a pluggable height-resolution layer that sits between
//! the raw OSM/GSI element data and the Minecraft building generator.
//!
//! # Architecture
//!
//! ```text
//! HeightProvider (trait)
//!   ├── Gsi3dProvider   — GSI 3D GML files (Phase 1)
//!   └── PlateauProvider — PLATEAU 3D Tiles API (Phase 2, stub)
//!
//! HeightResolver
//!   └── queries providers in priority order, returns first match
//! ```
//!
//! The resolver is constructed once per generation run and passed into the
//! building pipeline. This keeps the upstream-compatible `buildings.rs` diff
//! minimal: only the call-site of `calculate_building_height` gains an extra
//! optional parameter.

mod b3dm;
pub mod gsi_3d;
pub mod plateau;

/// Result of a height lookup from an external data source.
#[derive(Debug, Clone)]
pub struct HeightResult {
    /// Building height in metres.
    pub height_m: f64,
    /// Ground elevation in metres (if available).
    pub ground_elv_m: Option<f64>,
    /// Human-readable source label (e.g. "GSI-3D", "PLATEAU").
    pub source: &'static str,
}

/// A provider that can look up building heights by centroid coordinate.
pub trait HeightProvider: Send + Sync {
    /// Look up the height of a building whose centroid is at `(lat, lng)`.
    ///
    /// Returns `None` when no matching building is found within the
    /// provider's tolerance distance.
    fn lookup(&self, lat: f64, lng: f64) -> Option<HeightResult>;

    /// Human-readable name for logging.
    fn name(&self) -> &'static str;
}

/// Inverse-transform parameters for converting Minecraft XZ → lat/lng.
///
/// Derived from the forward transform in `CoordTransformer`:
///   x = ((lng - min_lng) / len_lng) * scale_factor_x
///   z = (1 - (lat - min_lat) / len_lat) * scale_factor_z
#[derive(Debug, Clone)]
struct InverseTransform {
    min_lat: f64,
    min_lng: f64,
    len_lat: f64,
    len_lng: f64,
    scale_factor_x: f64,
    scale_factor_z: f64,
}

impl InverseTransform {
    fn mc_to_latlng(&self, x: i32, z: i32) -> (f64, f64) {
        let rel_x = x as f64 / self.scale_factor_x;
        let rel_z = z as f64 / self.scale_factor_z;
        let lng = rel_x * self.len_lng + self.min_lng;
        let lat = (1.0 - rel_z) * self.len_lat + self.min_lat;
        (lat, lng)
    }
}

/// Priority-ordered resolver that queries multiple [`HeightProvider`]s.
///
/// Providers are tried in insertion order; the first match wins.
/// Includes an inverse coordinate transform so callers can query
/// using Minecraft XZ coordinates directly.
pub struct HeightResolver {
    providers: Vec<Box<dyn HeightProvider>>,
    inverse: InverseTransform,
}

impl HeightResolver {
    /// Create a resolver with coordinate transform parameters.
    ///
    /// The parameters match `CoordTransformer` fields and are used to
    /// convert Minecraft XZ back to lat/lng for provider lookups.
    pub fn new(
        min_lat: f64,
        min_lng: f64,
        len_lat: f64,
        len_lng: f64,
        scale_factor_x: f64,
        scale_factor_z: f64,
    ) -> Self {
        Self {
            providers: Vec::new(),
            inverse: InverseTransform {
                min_lat,
                min_lng,
                len_lat,
                len_lng,
                scale_factor_x,
                scale_factor_z,
            },
        }
    }

    /// Add a provider. Providers added first have higher priority.
    pub fn add_provider(&mut self, provider: Box<dyn HeightProvider>) {
        self.providers.push(provider);
    }

    /// Returns `true` when at least one provider is registered.
    pub fn has_providers(&self) -> bool {
        !self.providers.is_empty()
    }

    /// Query providers using geographic coordinates.
    pub fn resolve(&self, lat: f64, lng: f64) -> Option<HeightResult> {
        for provider in &self.providers {
            if let Some(result) = provider.lookup(lat, lng) {
                return Some(result);
            }
        }
        None
    }

    /// Query providers using Minecraft XZ coordinates.
    ///
    /// Internally converts to lat/lng via the inverse transform, then
    /// delegates to [`resolve`](Self::resolve).
    pub fn resolve_mc(&self, x: i32, z: i32) -> Option<HeightResult> {
        let (lat, lng) = self.inverse.mc_to_latlng(x, z);
        self.resolve(lat, lng)
    }

    /// How many providers are registered.
    pub fn provider_count(&self) -> usize {
        self.providers.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct DummyProvider {
        height: f64,
    }

    impl HeightProvider for DummyProvider {
        fn lookup(&self, _lat: f64, _lng: f64) -> Option<HeightResult> {
            Some(HeightResult {
                height_m: self.height,
                ground_elv_m: Some(10.0),
                source: "dummy",
            })
        }
        fn name(&self) -> &'static str {
            "dummy"
        }
    }

    struct EmptyProvider;

    impl HeightProvider for EmptyProvider {
        fn lookup(&self, _lat: f64, _lng: f64) -> Option<HeightResult> {
            None
        }
        fn name(&self) -> &'static str {
            "empty"
        }
    }

    fn make_resolver() -> HeightResolver {
        HeightResolver::new(34.0, 135.0, 0.01, 0.01, 1000.0, 1000.0)
    }

    #[test]
    fn test_resolver_priority() {
        let mut resolver = make_resolver();
        resolver.add_provider(Box::new(EmptyProvider));
        resolver.add_provider(Box::new(DummyProvider { height: 25.0 }));

        let result = resolver.resolve(35.0, 139.0).unwrap();
        assert!((result.height_m - 25.0).abs() < f64::EPSILON);
        assert_eq!(result.source, "dummy");
    }

    #[test]
    fn test_resolver_empty() {
        let resolver = make_resolver();
        assert!(resolver.resolve(35.0, 139.0).is_none());
        assert!(!resolver.has_providers());
    }

    #[test]
    fn test_first_provider_wins() {
        let mut resolver = make_resolver();
        resolver.add_provider(Box::new(DummyProvider { height: 10.0 }));
        resolver.add_provider(Box::new(DummyProvider { height: 99.0 }));

        let result = resolver.resolve(35.0, 139.0).unwrap();
        assert!((result.height_m - 10.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_inverse_transform_roundtrip() {
        let inv = InverseTransform {
            min_lat: 34.0,
            min_lng: 135.0,
            len_lat: 0.01,
            len_lng: 0.01,
            scale_factor_x: 1000.0,
            scale_factor_z: 1000.0,
        };

        // MC origin (0, 0) → max_lat, min_lng
        let (lat, lng) = inv.mc_to_latlng(0, 0);
        assert!((lat - 34.01).abs() < 1e-9); // max_lat = min_lat + len_lat
        assert!((lng - 135.0).abs() < 1e-9);

        // MC (1000, 1000) → min_lat, max_lng
        let (lat, lng) = inv.mc_to_latlng(1000, 1000);
        assert!((lat - 34.0).abs() < 1e-9);
        assert!((lng - 135.01).abs() < 1e-9);
    }
}
