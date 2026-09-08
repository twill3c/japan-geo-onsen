"""Wikidata から採った温泉点の検算(SPEC G-12)。

この層は P12(政府データ)とは**性格が違う**。悉皆調査ではなく、
「記事が書かれた温泉が載っている」データである。だから

- 出所を必ず属性に持ち、P12 の点と混ざらないこと
- 公開データに無い項目(泉質・泉温・湧出量)は P12 と同じく null のまま出すこと
- 統計(温泉と地理環境)には**使わない**こと

を検査で固定する。件数は raw の実物から数え直す(定数で書かない)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_onsen_base import UNAVAILABLE
from etl.build_onsen_wikidata import JAPAN_BBOX, RAW_QUERY, dedupe
from etl.common import DATA, haversine_km

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def raw_rows():
    return json.loads(RAW_QUERY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fc():
    return json.loads((DATA / "onsen_wikidata.geojson").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def p12():
    return json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))


def test_同じ項目の複数座標を畳んでいる(raw_rows):
    """出所: 実測 2026-09-08。行 2,338 に対し項目は 1,477。

    同じ温泉に座標が複数登録されていることがある。畳まずに出すと
    同じ場所に点が重なって数を水増しする。
    """
    qids = {r["qid"] for r in raw_rows}
    assert len(raw_rows) > len(qids), "重複が無いなら、この検査は空振りしている"
    assert len(dedupe(raw_rows)) == len(qids)


def test_出荷した点が生データの項目数と一致する(raw_rows, fc):
    kept = dedupe(raw_rows)
    inside = [r for r in kept
              if JAPAN_BBOX[0] <= r["lon"] <= JAPAN_BBOX[2]
              and JAPAN_BBOX[1] <= r["lat"] <= JAPAN_BBOX[3]]
    assert len(fc["features"]) == len(inside)
    assert {f["properties"]["wikidata_id"] for f in fc["features"]} == {r["qid"] for r in inside}


def test_全点が出所を持つ(fc):
    for f in fc["features"]:
        assert f["properties"]["provenance"] == "wikidata"
        assert f["properties"]["wikidata_id"].startswith("Q")


def test_公開データに無い項目は空のまま(fc):
    """SPEC G-03。P12 と同じく、値を作らない。"""
    assert UNAVAILABLE
    for f in fc["features"]:
        for key in UNAVAILABLE:
            assert key in f["properties"], f"{key} の欄そのものが無い"
            assert f["properties"][key] is None, f"{key} に値が入っている"


def test_名前が無い点は名前を作らない(fc):
    """ラベルが Q 番号のままの項目がある(実測 2026-09-08: 21 件)。

    Q 番号を名前として出すと、地図に「Q12345」と表示されてしまう。
    名前は null にして、画面側で「(名称なし)」と出す。
    """
    unnamed = [f for f in fc["features"] if f["properties"]["name"] is None]
    assert len(unnamed) > 0, "名前の無い項目が無いなら、この検査は空振りしている"
    for f in fc["features"]:
        n = f["properties"]["name"]
        assert n is None or not (n.startswith("Q") and n[1:].isdigit()), n
    assert fc["metadata"]["counts"]["unnamed"] == len(unnamed)


def test_全点が日本の範囲に収まる(fc):
    for f in fc["features"]:
        lon, lat = f["geometry"]["coordinates"]
        assert JAPAN_BBOX[0] <= lon <= JAPAN_BBOX[2]
        assert JAPAN_BBOX[1] <= lat <= JAPAN_BBOX[3]


def test_ID_が一意(fc):
    ids = [f["id"] for f in fc["features"]]
    assert len(ids) == len(set(ids))


def test_P12_と重なる点の数が記録されている(fc, p12):
    """重なりは消さない(出所が違うので、どちらも残す)。数だけ数えて残す。"""
    pts = [f["geometry"]["coordinates"] for f in p12["features"]]
    thr = fc["metadata"]["overlap"]["threshold_km"]
    near = 0
    for f in fc["features"]:
        lon, lat = f["geometry"]["coordinates"]
        if any(haversine_km(lon, lat, p[0], p[1]) <= thr for p in pts):
            near += 1
    assert near == fc["metadata"]["overlap"]["within_threshold"]
    assert fc["metadata"]["overlap"]["distinct_locations"] == len(pts) + len(fc["features"]) - near


def test_統計は_P12_だけで取られている():
    """SPEC の設計そのもの。対照群は同じ P12 から取っており、出所の違う点を混ぜない。"""
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    assert stats["generated_from"]["onsen"] == len(onsen["features"])
    # 統計に使う温泉点には wikidata 由来が 1 つも入っていないこと
    for f in onsen["features"]:
        assert f["properties"].get("provenance", "ksj-p12") != "wikidata"
