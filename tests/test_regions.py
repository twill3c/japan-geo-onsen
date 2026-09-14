"""地域比較の検算(SPEC G-21 / 設計書 §58)。

設計書は「八ヶ岳・富士山・箱根・草津・別府などを比較する」と地名を挙げるだけで、
地域の境界を定めていない。境界を推測で描かないため、この地図では
**基準点(Wikidata の項目、または気象庁の活火山)と半径**で地域を定める。

検算の軸:
- 基準点は設計書の語ごとに**ちょうど 1 つ**に決まり、同名の別物(富士山は 3 つある)を取らない
- 地域内の点の数は、各層のファイルを**総当たり**した数と一致する
- 植生メッシュの数は、円の面積 ÷ メッシュ 1 個の面積と合う(内陸の地域で)
- 割合の合計は 100%、要約の中央値は総当たりの集合の中央値と一致
- 半径を広げて数が減らない
- 円どうしが重なる地域の組は、重なっていると記録される(同じ温泉を両方で数えるため)
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_regions import (
    LAYERS, OUT, RADII_KM, SPEC_REGIONS, coverage_note, resolve_spec_anchors,
)
from etl.common import DATA, haversine_km

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def doc():
    return json.loads(OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def layers():
    return {key: json.loads((DATA / path).read_text(encoding="utf-8")) for key, path in LAYERS.items()}


def test_設計書の語ごとに基準点がちょうど1つ決まる():
    anchors = resolve_spec_anchors()
    assert [a["label"] for a in anchors] == [r["label"] for r in SPEC_REGIONS]
    assert [r["label"] for r in SPEC_REGIONS] == ["八ヶ岳", "富士山", "箱根", "草津", "別府"]
    for a in anchors:
        assert a["wikidata_id"].startswith("Q")
        assert 122 <= a["lon"] <= 154 and 20 <= a["lat"] <= 46.5, a


def test_同名の別物を基準点に取らない():
    """富士山は Wikidata に同名の山が 3 つある(茨城 152m・栃木 160m)。活火山の項目を取る。"""
    fuji = next(a for a in resolve_spec_anchors() if a["label"] == "富士山")
    assert fuji["wikidata_id"] == "Q39231"


def test_基準点と最寄りの活火山の距離が記録されている(doc):
    """基準点を火山にしなかった地域がどれだけ火山から離れているかを隠さない。"""
    by = {r["label"]: r for r in doc["regions"] if r["kind"] == "spec"}
    for label in ("八ヶ岳", "富士山", "箱根", "草津", "別府"):
        r = by[label]
        assert r["nearest_volcano"]["name"]
        assert r["nearest_volcano"]["distance_km"] >= 0
    # 富士山の基準点は気象庁の富士山とほぼ同じ場所
    assert by["富士山"]["nearest_volcano"]["name"] == "富士山"
    assert by["富士山"]["nearest_volcano"]["distance_km"] < 1.0


@pytest.mark.parametrize("radius", RADII_KM)
def test_地域内の点の数が総当たりと一致する(radius, doc, layers):
    for r in doc["regions"]:
        if r["kind"] != "spec":
            continue
        stats = r["by_radius"][str(radius)]
        for key, fc in layers.items():
            want = sum(
                1 for f in fc["features"]
                if haversine_km(r["lon"], r["lat"], *f["geometry"]["coordinates"]) <= radius
            )
            assert stats["points"][key] == want, (r["label"], radius, key)


def test_火山を基準点にした地域も総当たりと一致する(doc, layers):
    """111 火山の中から 3 つだけ抜き取って確かめる(全部やると重い)。"""
    volcano_regions = [r for r in doc["regions"] if r["kind"] == "volcano"]
    assert len(volcano_regions) == 111
    for r in volcano_regions[::40]:
        stats = r["by_radius"]["10"]
        fc = layers["ksj"]
        want = sum(1 for f in fc["features"]
                   if haversine_km(r["lon"], r["lat"], *f["geometry"]["coordinates"]) <= 10)
        assert stats["points"]["ksj"] == want, r["label"]


def test_植生メッシュの数が円の面積と合う(doc):
    """外部の物差し: 3 次メッシュ 1 個は 緯度 30 秒 × 経度 45 秒。

    内陸の八ヶ岳で、半径 10 km の円に入るメッシュの数は、面積の比でほぼ決まる。
    """
    r = next(x for x in doc["regions"] if x["label"] == "八ヶ岳")
    n = r["by_radius"]["10"]["vegetation_meshes"]
    km_lat = 6371.0088 * math.pi / 180
    mesh_area = (km_lat * 30 / 3600) * (km_lat * math.cos(math.radians(r["lat"])) * 45 / 3600)
    expected = math.pi * 10 ** 2 / mesh_area
    assert abs(n - expected) / expected < 0.03, (n, expected)


def test_割合の合計が100パーセント(doc):
    for r in doc["regions"]:
        for radius, s in r["by_radius"].items():
            if s["vegetation_meshes"] > 0:
                assert sum(s["vegetation_share"].values()) == pytest.approx(1.0, abs=1e-9), (r["label"], radius)
            if s["onsen_summary"]["n"] > 0:
                assert sum(s["onsen_summary"]["geology_share"].values()) == pytest.approx(1.0, abs=1e-9)


def test_温泉の要約の中央値が総当たりと一致する(doc, layers):
    """要約は国土数値情報の層だけで取る(出所を混ぜない)。"""
    fc = layers["ksj"]
    for r in doc["regions"]:
        if r["kind"] != "spec":
            continue
        s = r["by_radius"]["25"]["onsen_summary"]
        inside = [f["properties"] for f in fc["features"]
                  if haversine_km(r["lon"], r["lat"], *f["geometry"]["coordinates"]) <= 25]
        assert s["n"] == len(inside)
        elev = [p["elevation_m"] for p in inside if p.get("elevation_m") is not None]
        if elev:
            assert s["elevation_median_m"] == pytest.approx(statistics.median(elev), abs=1e-9)
        else:
            assert s["elevation_median_m"] is None


def test_半径を広げて数が減らない(doc):
    for r in doc["regions"]:
        a, b = r["by_radius"]["10"], r["by_radius"]["25"]
        for key in LAYERS:
            assert b["points"][key] >= a["points"][key], (r["label"], key)
        assert b["lakes"] >= a["lakes"] and b["volcanoes"] >= a["volcanoes"]
        assert b["vegetation_meshes"] >= a["vegetation_meshes"]


def test_円の重なる組が記録されている(doc):
    """富士山(Q39231)と箱根温泉(Q908993)の基準点は 32.8 km。半径 25 km の円は重なる。

    最初この docstring とページ本文に「約 27 km」と書いていた。実測する前の見込みで、
    基準点を気象庁の火山どうしと取り違えていた。
    """
    ov = {tuple(sorted(p["pair"])) for p in doc["overlaps"]["25"]}
    assert ("富士山", "箱根") in ov or ("箱根", "富士山") in ov
    # 別府と八ヶ岳は重ならない
    assert not any(set(p["pair"]) == {"別府", "八ヶ岳"} for p in doc["overlaps"]["25"])


def test_被覆の穴の注記():
    """観光資源データに点が無いのに他の出所に点がある地域は、穴の可能性として注記する。"""
    hole = coverage_note({"ksj": 0, "wikidata": 3, "facility": 0, "wikipedia": 2})
    assert hole is not None and "穴" in hole
    assert coverage_note({"ksj": 0, "wikidata": 0, "facility": 0, "wikipedia": 0}) is None
    assert coverage_note({"ksj": 12, "wikidata": 3, "facility": 0, "wikipedia": 2}) is None


def test_点が少なすぎる要約にも注記する():
    """0 だけを見る規則では、P12 が 3 点しか無い別府の要約を黙って出していた。"""
    small = coverage_note({"ksj": 3, "wikidata": 22, "facility": 2, "wikipedia": 11})
    assert small is not None and "参考" in small
    assert coverage_note({"ksj": 5, "wikidata": 22, "facility": 2, "wikipedia": 11}) is None


def test_別府の要約に注記が付いている(doc):
    beppu = next(r for r in doc["regions"] if r["label"] == "別府")
    s = beppu["by_radius"]["25"]
    assert s["onsen_summary"]["n"] < 5
    assert s["coverage_note"] and "参考" in s["coverage_note"]
