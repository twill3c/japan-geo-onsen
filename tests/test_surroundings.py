"""周辺環境分析の検算(SPEC G-19 / 設計書 §56)。

半径内を数えるのに格子で候補を絞っている。**近道の答えが、近道をしない総当たりと
完全に一致すること**を実データで確かめる(速さを変えたら答えが変わっていないことを
総当たりで確かめる —— G-10 と同じ形)。

加えて、数そのものの性質:
- 半径を広げて数が減ることはない
- 植生の帯の合計がメッシュ数に一致する(取りこぼし・二重計上なし)
- 自分自身は数えない
- 湖沼は中心でなく縁までの距離で測っている
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_surroundings import (
    BANDS, COLUMNS, RADII_KM, Context, MeshIndex, PointGrid,
    lake_distance_km, surroundings,
)
from etl.build_vegetation import load_mesh, load_tables
from etl.common import DATA, haversine_km
from etl.mesh import mesh3_center

pytestmark = pytest.mark.validation
SEED = 20260914


def _grid(path: str) -> PointGrid:
    fc = json.loads((DATA / path).read_text(encoding="utf-8"))
    return PointGrid([
        (f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
         str(f["properties"].get("onsen_id") or f["properties"].get("name") or i))
        for i, f in enumerate(fc["features"])
    ])


@pytest.fixture(scope="module")
def mesh_raw():
    return load_mesh()


@pytest.fixture(scope="module")
def mesh_index(mesh_raw):
    return MeshIndex(mesh_raw)


@pytest.fixture(scope="module")
def onsen_grid():
    return _grid("onsen.geojson")


def _probe_points(n: int) -> list[tuple[float, float]]:
    """実在の温泉点から取る(海の真ん中で一致しても意味が薄い)。"""
    fc = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    return [tuple(f["geometry"]["coordinates"]) for f in rng.sample(fc["features"], n)]


@pytest.mark.parametrize("km", RADII_KM)
def test_点の格子が総当たりと一致する(km, onsen_grid):
    for lon, lat in _probe_points(25):
        got = sorted((k, round(d, 9)) for k, d in onsen_grid.within(lon, lat, km))
        want = sorted(
            (k, round(haversine_km(lon, lat, p[0], p[1]), 9))
            for k, p in enumerate(onsen_grid.items)
            if haversine_km(lon, lat, p[0], p[1]) <= km
        )
        assert got == want, (lon, lat, km)


def test_北の端でも点の格子が漏らさない():
    """経度 1 度が短い高緯度では、箱の幅を中心の緯度で決めると端を取りこぼす。"""
    rng = random.Random(SEED)
    items = [(141.0 + rng.uniform(-1.5, 1.5), 45.2 + rng.uniform(-0.6, 0.6), str(i)) for i in range(400)]
    g = PointGrid(items)
    for km in (25, 50):
        got = {k for k, _ in g.within(141.0, 45.2, km)}
        want = {k for k, p in enumerate(items) if haversine_km(141.0, 45.2, p[0], p[1]) <= km}
        assert got == want


def test_メッシュの行列が中心座標と往復する(mesh_raw, mesh_index):
    rng = random.Random(SEED)
    codes = rng.sample(sorted(mesh_raw), 500)
    for code in codes:
        lon, lat = mesh3_center(code)
        r = round(lat / (1 / 120) - 0.5)
        c = round(lon / (1 / 80) - 0.5)
        clon, clat = MeshIndex.center(r, c)
        assert clon == pytest.approx(lon, abs=1e-9) and clat == pytest.approx(lat, abs=1e-9), code
        assert mesh_index.by_rc[(r, c)] == mesh_raw[code]
    assert len(mesh_index.by_rc) == len(mesh_raw), "行列の鍵が衝突している"


@pytest.mark.parametrize("km", [5, 25])
def test_メッシュの格子が総当たりと一致する(km, mesh_raw, mesh_index):
    """全 368,727 メッシュを総当たりする。重いので点は 3 つに絞る。"""
    # 索引はメッシュ中心を (列+0.5)×45秒 で作り、総当たりはコードから mesh3_center で作る。
    # 同じ点でも浮動小数の足し方が違うので、距離は 1e-15 の桁でずれる。
    # 最初は距離を小数第 9 位で丸めて比べ、7.979142204 と 7.979142205 が丸めの境界を
    # またいで落ちた(**実装ではなく比べ方の誤り**)。メッシュの並びは完全一致で比べ、
    # 距離だけ許容差で比べる。同じ群落コードのメッシュどうしは 1 km 近く離れているので、
    # (コード, 距離) で並べた順は許容差の範囲で入れ替わらない。
    centers = [(mesh3_center(code), gun) for code, gun in mesh_raw.items()]
    for lon, lat in _probe_points(3):
        got = sorted(mesh_index.within(lon, lat, km))
        want = sorted(
            (gun, haversine_km(lon, lat, c[0], c[1]))
            for c, gun in centers
            if abs(c[1] - lat) < 1 and abs(c[0] - lon) < 1.5
            and haversine_km(lon, lat, c[0], c[1]) <= km
        )
        assert [g for g, _ in got] == [g for g, _ in want], (lon, lat, km)
        for (_, d1), (_, d2) in zip(got, want):
            assert abs(d1 - d2) < 1e-9, (lon, lat, km, d1, d2)


def test_湖沼は縁までの距離で測る():
    """1 km 四方の正方形の湖。東の縁から東へ 3 km の点は、中心からなら 3.5 km。"""
    lon0, lat0 = 138.0, 36.0
    dlat = 1.0 / 111.195
    dlon = 1.0 / (111.195 * math.cos(math.radians(lat0)))
    ring = [(lon0, lat0), (lon0 + dlon, lat0), (lon0 + dlon, lat0 + dlat), (lon0, lat0 + dlat)]
    px = lon0 + dlon + 3 * dlon
    py = lat0 + dlat / 2
    d = lake_distance_km(px, py, [ring])
    assert d == pytest.approx(3.0, abs=0.02)


@pytest.fixture(scope="module")
def ctx(mesh_index):
    from etl.build_surroundings import load_lakes

    gunraku, _, _ = load_tables()
    return Context(
        volcanoes=_grid("volcanoes.geojson"), ksj=_grid("onsen.geojson"),
        wikidata=_grid("onsen_wikidata.geojson"), lakes=load_lakes(),
        mesh=mesh_index, gunraku=gunraku,
    )


def test_半径を広げて数が減らず帯の合計がメッシュ数に一致する(ctx):
    fc = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    col = {name: i for i, name in enumerate(COLUMNS)}
    for f in rng.sample(fc["features"], 8):
        lon, lat = f["geometry"]["coordinates"]
        rows = surroundings(lon, lat, ctx, self_id=f["properties"]["onsen_id"])
        assert len(rows) == len(RADII_KM)
        for i in range(1, len(rows)):
            for j in range(len(COLUMNS)):
                assert rows[i][j] >= rows[i - 1][j], (f["properties"]["onsen_id"], COLUMNS[j])
        for row in rows:
            assert sum(row[col[b]] for b in BANDS) == row[col["vegetation_meshes"]]


def test_自分自身は数えない(ctx):
    """同じ点を、自分の ID を渡した場合と渡さない場合で比べる。差はちょうど 1。"""
    f = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))["features"][0]
    lon, lat = f["geometry"]["coordinates"]
    mine = surroundings(lon, lat, ctx, self_id=f["properties"]["onsen_id"])
    other = surroundings(lon, lat, ctx, self_id="(別の点)")
    k = COLUMNS.index("onsen_ksj")
    for a, b in zip(mine, other):
        assert b[k] - a[k] == 1


def test_火山の真上なら_5km_に_1_つ以上ある(ctx):
    """陽性対照。数え方が空振りしていないこと。"""
    v = ctx.volcanoes.items[0]
    rows = surroundings(v[0], v[1], ctx, self_id=None)
    assert rows[0][COLUMNS.index("volcanoes")] >= 1
