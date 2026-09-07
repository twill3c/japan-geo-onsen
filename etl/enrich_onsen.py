"""温泉点に 標高・傾斜・地質・最寄り火山 を付ける(設計書 §13/§14/§17)。

- 標高/傾斜/起伏: 国土地理院 標高タイル dem_png(z=14, DEM10B 相当)を実測して算出
- 地質: 産総研 シームレス地質図V2 Web API 1.3 の凡例取得サービス(点指定)
- 火山距離: data/volcanoes.geojson との球面距離(独立実装の測地線距離で検算 — G-08)

外部への問い合わせは一度だけ行い raw/ にキャッシュする(設計書 §44 原則6)。
"""
from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from etl.common import (DATA, RAW, decode_dem_rgb, fetch, haversine_km,
                        lonlat_to_pixel, tile_pixel_size_m, vincenty_km,
                        write_json)

DEM_Z = 14
DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"
GSJ_URL = "https://gbank.gsj.jp/seamless/v2/api/1.3/legend.json?point={lat},{lon}"
RELIEF_RADIUS_PX = 16  # ±16 画素 ≈ ±125 m(z=14, 北緯 35 度)

_tiles: dict[tuple[int, int], list[list[float | None]] | None] = {}


def dem_tile(x: int, y: int) -> list[list[float | None]] | None:
    """標高タイル 1 枚を [j][i] の標高配列にする。存在しなければ None。"""
    key = (x, y)
    if key in _tiles:
        return _tiles[key]
    dest = RAW / "gsi" / "dem_png" / str(DEM_Z) / str(x) / f"{y}.png"
    body = fetch(DEM_URL.format(z=DEM_Z, x=x, y=y), dest, sleep=0.15)
    if body is None:
        _tiles[key] = None
        return None
    im = Image.open(io.BytesIO(body)).convert("RGB")
    px = im.load()
    grid = [[decode_dem_rgb(*px[i, j]) for i in range(256)] for j in range(256)]
    _tiles[key] = grid
    return grid


def sample(x: int, y: int, i: int, j: int) -> float | None:
    """タイル境界をまたぐ画素参照を吸収して標高を返す。"""
    x += i // 256
    y += j // 256
    grid = dem_tile(x, y)
    if grid is None:
        return None
    return grid[j % 256][i % 256]


def terrain(lon: float, lat: float) -> dict:
    x, y, i, j = lonlat_to_pixel(lon, lat, DEM_Z)
    elev = sample(x, y, i, j)
    out: dict = {"elevation_m": None, "slope_deg": None, "aspect_deg": None,
                 "local_relief_m": None, "elevation_source": f"GSI dem_png z{DEM_Z}"}
    if elev is None:
        return out
    out["elevation_m"] = round(elev, 1)

    # 傾斜・斜面方位(Horn 法)。3x3 のいずれかが欠けたら出さない
    z_ = [[sample(x, y, i + di, j + dj) for di in (-1, 0, 1)] for dj in (-1, 0, 1)]
    if all(v is not None for row in z_ for v in row):
        dx, dy = tile_pixel_size_m(y, DEM_Z, j)
        dzdx = ((z_[0][2] + 2 * z_[1][2] + z_[2][2]) - (z_[0][0] + 2 * z_[1][0] + z_[2][0])) / (8 * dx)
        dzdy = ((z_[2][0] + 2 * z_[2][1] + z_[2][2]) - (z_[0][0] + 2 * z_[0][1] + z_[0][2])) / (8 * dy)
        out["slope_deg"] = round(math.degrees(math.atan(math.hypot(dzdx, dzdy))), 2)
        a = math.degrees(math.atan2(dzdy, -dzdx))
        out["aspect_deg"] = round((90.0 - a) % 360.0, 1)

    # 局所起伏: ±RELIEF_RADIUS_PX の窓の最大 − 最小
    vals = [v for dj in range(-RELIEF_RADIUS_PX, RELIEF_RADIUS_PX + 1, 4)
            for di in range(-RELIEF_RADIUS_PX, RELIEF_RADIUS_PX + 1, 4)
            if (v := sample(x, y, i + di, j + dj)) is not None]
    if len(vals) >= 9:
        out["local_relief_m"] = round(max(vals) - min(vals), 1)
        out["local_relief_window_m"] = round(2 * RELIEF_RADIUS_PX * tile_pixel_size_m(y, DEM_Z, j)[0])
    return out


def geology(lon: float, lat: float) -> dict:
    dest = RAW / "gsj" / "legend" / f"{lat:.6f}_{lon:.6f}.json"
    body = fetch(GSJ_URL.format(lat=f"{lat:.6f}", lon=f"{lon:.6f}"), dest, sleep=0.35)
    if body is None:
        return {}
    d = json.loads(body.decode("utf-8"))
    # 凡例が引けない地点がある(実測 2026-09-07: 1,320 点中 1 点。symbol も色も null で
    # 返る)。色を作らずそのまま欠測にする — 架空の地質を出さない(SPEC G-01/G-03)。
    if not d or d.get("symbol") is None:
        return {"geology_symbol": None, "geology_group": None, "geology_lithology": None,
                "geology_age": None, "geology_color": None}
    r, g, b = d.get("r"), d.get("g"), d.get("b")
    color = f"#{r:02x}{g:02x}{b:02x}" if None not in (r, g, b) else None
    return {
        "geology_symbol": d.get("symbol"),
        "geology_group": d.get("group_ja"),
        "geology_lithology": d.get("lithology_ja"),
        "geology_age": d.get("formationAge_ja"),
        "geology_color": color,
    }


def main(target: str = "onsen.geojson") -> None:
    path = DATA / target
    onsen = json.loads(path.read_text(encoding="utf-8"))
    volc = json.loads((DATA / "volcanoes.geojson").read_text(encoding="utf-8"))
    vs = [(f["properties"]["name"], *f["geometry"]["coordinates"]) for f in volc["features"]]

    worst = 0.0
    for n, f in enumerate(onsen["features"], 1):
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        p.update(terrain(lon, lat))
        p.update(geology(lon, lat))

        name, vlon, vlat = min(vs, key=lambda v: haversine_km(lon, lat, v[1], v[2]))
        d_h = haversine_km(lon, lat, vlon, vlat)
        d_v = vincenty_km(lon, lat, vlon, vlat)
        worst = max(worst, abs(d_h - d_v) / max(d_v, 1e-9))
        p["nearest_volcano"] = name
        p["distance_to_volcano_km"] = round(d_h, 2)
        # 注意: これは地理的距離であって因果関係ではない(設計書 §14)
        if n % 100 == 0:
            print(f"  {n}/{len(onsen['features'])}", flush=True)

    onsen["metadata"]["enrichment"] = {
        "elevation": {"source": "国土地理院 標高タイル(dem_png)",
                      "source_url": "https://maps.gsi.go.jp/development/demtile.html",
                      "zoom": DEM_Z, "download_date": "2026-09-07"},
        "geology": {"source": "産業技術総合研究所 地質調査総合センター",
                    "dataset": "20万分の1日本シームレス地質図V2 Web API 1.3(凡例取得サービス)",
                    "source_url": "https://gbank.gsj.jp/seamless/v2/api/1.3/",
                    "download_date": "2026-09-07"},
        "volcano_distance": {"method": "球面(半径6371.0088km)の大円距離",
                             "cross_check": "WGS84 測地線(Vincenty)との相対差",
                             "max_relative_difference": worst},
    }
    write_json(path, onsen)
    got = sum(1 for f in onsen["features"] if f["properties"].get("elevation_m") is not None)
    geo = sum(1 for f in onsen["features"] if f["properties"].get("geology_symbol"))
    print(f"完了 {target}: 標高 {got}/{len(onsen['features'])}  地質 {geo}/{len(onsen['features'])}")
    print(f"距離の二実装相対差 最大 {worst:.6f}  (取得タイル {len([v for v in _tiles.values() if v])} 枚)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "onsen.geojson")
