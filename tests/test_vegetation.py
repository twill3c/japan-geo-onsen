"""植生データの取り込みの検算(SPEC G-13)。

期待値の出所はすべて raw の実物である。件数は定数で書かず、
**生データから数え直したものと一致すること**を言う(HC-016)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_vegetation import load_mesh, load_tables
from etl.common import DATA
from etl.mesh import point_to_mesh3

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def tables():
    return load_tables()


@pytest.fixture(scope="module")
def mesh():
    return load_mesh()


@pytest.fixture(scope="module")
def stats():
    return json.loads((DATA / "vegetation_stats.json").read_text(encoding="utf-8"))


def test_メッシュ件数が生データと一致する(mesh, stats):
    assert stats["counts"]["meshes"] == len(mesh)
    assert len(mesh) > 300000, "3 次メッシュが少なすぎる"


def test_使われている群落コードがすべて群落表で引ける(mesh, tables):
    """引けないコードが 1 つでもあれば ETL は止まる。ここでも数で押さえる。"""
    gunraku, _, _ = tables
    used = {c for c in mesh.values()}
    assert used, "群落コードが空なら、この検査は空振りしている"
    assert not (used - set(gunraku))


def test_自然度がすべて凡例にある(mesh, tables):
    gunraku, sizendo, _ = tables
    used = {gunraku[c]["sizendo"] for c in mesh.values()}
    assert not (used - set(sizendo))


def test_自然度の内訳がメッシュ総数と一致する(stats):
    """凡例に付けたメッシュ数の合計が総数に一致すること(取りこぼしの検査)。"""
    total = sum(r["meshes"] for r in stats["sizendo_legend"])
    assert total == stats["counts"]["meshes"]


def test_自然度の段階が1から10まで揃っている(stats):
    """出所: 凡例(veg_sizendo.csv)。1〜10 の段階に加えて 00/98/99 がある。"""
    codes = {r["code"] for r in stats["sizendo_legend"]}
    assert {f"{i:02d}" for i in range(1, 11)} <= codes
    assert {"00", "98", "99"} <= codes
    # 1〜10 のすべてに実際のメッシュがあること(空の段階が無い)
    for r in stats["sizendo_legend"]:
        if r["code"].isdigit() and 1 <= int(r["code"]) <= 10:
            assert r["meshes"] > 0, r


@pytest.mark.parametrize("path", ["onsen.geojson", "control.geojson", "onsen_wikidata.geojson"])
def test_点に付けた植生がメッシュから引き直せる(path, mesh, tables):
    """出荷した属性が、その点の座標から独立に再現できること。"""
    gunraku, sizendo, _ = tables
    fc = json.loads((DATA / path).read_text(encoding="utf-8"))
    checked = 0
    for f in fc["features"]:
        pr = f["properties"]
        assert "vegetation_naturalness" in pr, "植生の欄が無い"
        lon, lat = f["geometry"]["coordinates"]
        code = point_to_mesh3(lon, lat)
        assert pr["vegetation_mesh"] == code
        g = gunraku.get(mesh.get(code, ""))
        if g is None:
            # メッシュが無い点は埋めない
            assert pr["vegetation_naturalness"] is None
            assert pr["vegetation_community"] is None
            continue
        checked += 1
        assert pr["vegetation_naturalness"] == g["sizendo"]
        assert pr["vegetation_community"] == g["name"]
        assert pr["vegetation_naturalness_label"] == sizendo[g["sizendo"]]["content"]
    assert checked > 1000, f"照合できた点が {checked} 件しかない"


def test_メッシュが無い点がある(tables, mesh):
    """欠測が実在することの確認。0 件ならこの経路は一度も試されていない。"""
    gunraku, _, _ = tables
    fc = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    missing = [f for f in fc["features"] if f["properties"]["vegetation_naturalness"] is None]
    assert len(missing) > 0, "欠測が無いなら、欠測の扱いは一度も試されていない"
    for f in missing:
        lon, lat = f["geometry"]["coordinates"]
        assert point_to_mesh3(lon, lat) not in mesh or mesh[point_to_mesh3(lon, lat)] not in gunraku


def test_統計の植生軸が欠測を分母に入れていない():
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    veg = next(a for a in stats["axes"] if a["key"] == "vegetation")
    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    have = sum(1 for f in onsen["features"] if f["properties"]["vegetation_naturalness"] is not None)
    assert veg["onsen_n"] == have
    assert veg["onsen_missing"] == len(onsen["features"]) - have
