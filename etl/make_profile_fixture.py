"""地形断面の二実装照合フィクスチャを作る(SPEC G-14)。

tests-js/fixtures/dem_tiles.json に既に入っている**実タイル**の上に断面線を引き、
Python 参照実装(etl/profile_ref.py)の出した点列を書き出す。
TypeScript 側(lib/profile.ts)が同じ点列を出せば、両実装は一致している。

タイルの PNG は dem_tiles.json のものを使い回す —— 同じバイト列を二度リポジトリに
置かない。線はタイルの内側に収め、1 枚で完結させる(取得の都合をテストに持ち込まない)。
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from etl.common import REPO, decode_dem_rgb, write_json
from etl.profile_ref import haversine_km, pixel_resolution_m, profile

TILES = REPO / "tests-js" / "fixtures" / "dem_tiles.json"
OUT = REPO / "tests-js" / "fixtures" / "profile.json"

# 使うタイル。起伏の大きいもの(八ヶ岳周辺 z14)を対角に、
# 海に接して欠測のあるもの(欠測は北の縁 j=0〜24 に集まっている・実測)を
# **その帯を横切る向き**に引く。欠測を通らない線しか試さなければ、
# 欠測の扱いは一度も試されていないことになる。
PICK = [
    {"tile": "14/14463/6387", "shape": "diagonal"},
    {"tile": "14/14573/6156", "shape": "north-band"},
]
COUNT = 120


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    import math
    n = 2 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


def main() -> None:
    doc = json.loads(TILES.read_text(encoding="utf-8"))
    by_path = {t["path"]: t for t in doc["tiles"]}

    lines = []
    for spec in PICK:
        path, shape = spec["tile"], spec["shape"]
        t = by_path[path]
        z, x, y = (int(v) for v in path.split("/"))
        im = Image.open(io.BytesIO(base64.b64decode(t["png_base64"]))).convert("RGB")
        px = im.load()

        def lookup(tx: int, ty: int, i: int, j: int) -> float | None:
            if (tx, ty) != (x, y):
                return None       # タイルの外は埋めない
            return decode_dem_rgb(*px[i, j])

        west, south, east, north = tile_bounds(z, x, y)
        # 端の 1 画素に寄らないよう内側に入れる
        mx = (east - west) / 256 * 2
        my = (north - south) / 256 * 2
        if shape == "diagonal":
            a = (west + mx, south + my)
            b = (east - mx, north - my)
        else:
            # 北の縁の欠測帯(j=0〜24)を横切る水平線
            lat = north - (north - south) / 256 * 10
            a = (west + mx, lat)
            b = (east - mx, lat)

        pts = profile(a[0], a[1], b[0], b[1], COUNT, z, lookup)
        vals = [p["elevation"] for p in pts if p["elevation"] is not None]
        lines.append({
            "tile": path,
            "a": [a[0], a[1]],
            "b": [b[0], b[1]],
            "zoom": z,
            "count": COUNT,
            "length_km": haversine_km(a[0], a[1], b[0], b[1]),
            "pixel_resolution_m": pixel_resolution_m(z, (a[1] + b[1]) / 2),
            "valid": len(vals),
            "min_m": min(vals) if vals else None,
            "max_m": max(vals) if vals else None,
            "samples": [
                {
                    "t": p["t"],
                    "lon": p["lon"],
                    "lat": p["lat"],
                    "distance_km": p["distance_km"],
                    "i": p["i"],
                    "j": p["j"],
                    "elevation": p["elevation"],
                }
                for p in pts
            ],
        })

    write_json(OUT, {
        "note": ("地形断面の二実装照合。tests-js/fixtures/dem_tiles.json の実タイルの上に "
                 "A→B を引き、Python 参照実装(etl/profile_ref.py)が出した点列を写したもの。"),
        "source": "国土地理院 標高タイル(dem_png)",
        "source_url": "https://maps.gsi.go.jp/development/demtile.html",
        "generator": "etl/make_profile_fixture.py",
        "lines": lines,
    }, indent=1)

    for ln in lines:
        print(f"{ln['tile']}: {ln['length_km']:.3f} km / {ln['count']} 点 / "
              f"標高 {ln['min_m']}〜{ln['max_m']} m / 有効 {ln['valid']}")


if __name__ == "__main__":
    main()
