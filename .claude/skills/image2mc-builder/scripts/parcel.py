"""
敷地（施工してよい範囲）とポリゴン操作。

座標は Minecraft の (x, z)。セル (x, z) は中心 (x+0.5, z+0.5) がポリゴン内なら「中」とみなす。
敷地は、正式な site_data.json ができるまでは arnis が保存した OSM JSON から作る。
"""

import json
from pathlib import Path

import config


def point_in_polygon(x, z, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        if (z1 > z) != (z2 > z):
            xc = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
            if x < xc:
                inside = not inside
    return inside


def cells_in(poly, clip=None) -> set:
    """ポリゴン内のセル集合。clip=(x0,z0,x1,z1) で範囲を絞る（両端含む）。"""
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    x0, x1 = int(min(xs)) - 1, int(max(xs)) + 1
    z0, z1 = int(min(zs)) - 1, int(max(zs)) + 1
    if clip:
        x0, z0 = max(x0, clip[0]), max(z0, clip[1])
        x1, z1 = min(x1, clip[2]), min(z1, clip[3])
    return {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)
            if point_in_polygon(x + 0.5, z + 0.5, poly)}


def outline(cells: set) -> dict:
    """外周セル → 外に面している向きのリスト（'n','s','w','e'）。"""
    out = {}
    for (x, z) in cells:
        d = [k for k, (dx, dz) in {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}.items()
             if (x + dx, z + dz) not in cells]
        if d:
            out[(x, z)] = d
    return out


def dilate(cells: set, r: int = 1) -> set:
    """セル集合を r マス（8近傍）広げる。"""
    res = set(cells)
    for _ in range(r):
        res |= {(x + dx, z + dz) for (x, z) in res for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
    return res


def distance_inward(cells: set) -> dict:
    """各セルの、外周からの距離（外周=0、4近傍で数える）。"""
    dist = {}
    frontier = [c for c in cells if any((c[0] + dx, c[1] + dz) not in cells
                                        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    for c in frontier:
        dist[c] = 0
    d = 0
    while frontier:
        d += 1
        nxt = []
        for (x, z) in frontier:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, z + dz)
                if n in cells and n not in dist:
                    dist[n] = d
                    nxt.append(n)
        frontier = nxt
    return dist


class OsmGeometry:
    """arnis が保存した OSM JSON から、way のポリゴンを Minecraft 座標で取り出す。"""

    def __init__(self, osm_json: Path = None, world: Path = None):
        """osm_json・world を省くと設定（config.json）の OSM データとワールド。"""
        osm_json = osm_json or config.osm_json()
        world = world or config.world()
        m = json.loads((world / "world_mapping.json").read_text(encoding="utf-8"))
        self.m = m
        els = json.loads(osm_json.read_text(encoding="utf-8"))["elements"]
        self.nodes = {e["id"]: e for e in els if e["type"] == "node"}
        self.ways = {e["id"]: e for e in els if e["type"] == "way"}

    def to_mc(self, lat, lon):
        m = self.m
        return ((lon - m["min_lng"]) / m["len_lng"] * m["scale_factor_x"],
                (1 - (lat - m["min_lat"]) / m["len_lat"]) * m["scale_factor_z"])

    def polygon(self, way_id: int):
        w = self.ways[way_id]
        pts = [self.to_mc(self.nodes[n]["lat"], self.nodes[n]["lon"]) for n in w["nodes"]]
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        return pts
