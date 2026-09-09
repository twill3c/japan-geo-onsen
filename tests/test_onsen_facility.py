"""Wikidata の入浴施設を採った第三の層の検算(SPEC G-12 / G-17)。

この層は**温泉の層ではない**。「入浴施設として登録された場所」であって、
銭湯・公衆浴場も入る。だから

- 出所(`provenance`)を必ず持ち、温泉の 2 層と混ざらないこと
- 分類(`facility_class`)を持ち、何として登録されたものかを画面に出せること
- 公開データに無い項目(泉質・泉温・湧出量)は他の層と同じく null のまま出すこと
- 統計(温泉と地理環境)には**使わない**こと

を検査で固定する。件数は raw の実物から数え直す(定数で書かない)。

この層を足した経緯そのもの(ほったらかし温泉が 2 層のどちらにも入らない)も
検査に書いてある —— 経緯を文章だけに残すと、次の変更で静かに消える。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_onsen_base import UNAVAILABLE
from etl.build_onsen_facility import JAPAN_BBOX, RAW_QUERY, dedupe
from etl.common import DATA, haversine_km

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def raw_rows():
    return json.loads(RAW_QUERY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fc():
    return json.loads((DATA / "onsen_facility.geojson").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def wd():
    return json.loads((DATA / "onsen_wikidata.geojson").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def p12():
    return json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))


def test_出荷した点が生データの項目数と一致する(raw_rows, fc):
    """行(分類ごとに複数行になる)を畳んだ項目数と、出荷点数が合うこと。"""
    items = dedupe(raw_rows)
    w, s, e, n = JAPAN_BBOX
    inside = [r for r in items if w <= r["lon"] <= e and s <= r["lat"] <= n]
    assert len(fc["features"]) == len(inside)
    assert fc["metadata"]["counts"]["raw_rows"] == len(raw_rows)
    assert fc["metadata"]["counts"]["distinct_items"] == len(items)


def test_全点が出所と分類を持つ(fc):
    for f in fc["features"]:
        p = f["properties"]
        assert p["provenance"] == "wikidata-facility"
        assert p["onsen_id"].startswith("wdf-")
        assert p["wikidata_id"].startswith("Q")
        # 分類が無いなら、なぜ入っているのか説明できない
        assert p["facility_class"], p


def test_公開データに無い項目は空のまま(fc):
    for f in fc["features"]:
        for k in UNAVAILABLE:
            assert f["properties"][k] is None, (f["properties"]["onsen_id"], k)


def test_全点が日本の範囲に収まる(fc):
    w, s, e, n = JAPAN_BBOX
    for f in fc["features"]:
        lon, lat = f["geometry"]["coordinates"]
        assert w <= lon <= e and s <= lat <= n, f["properties"]["onsen_id"]


def test_ID_が一意(fc):
    ids = [f["properties"]["onsen_id"] for f in fc["features"]]
    assert len(ids) == len(set(ids))


def test_温泉の層と項目が重ならない(fc, wd):
    """クエリで温泉クラスを除いてある。**同じ Q 番号が二つの層に出ない**こと。"""
    a = {f["properties"]["wikidata_id"] for f in fc["features"]}
    b = {f["properties"].get("wikidata_id") for f in wd["features"]}
    assert not (a & b)


def test_場所が重なる点は消していないが数は記録されている(fc, p12, wd):
    """出所が違うので両方残す。数だけ数えて残す(温泉の層と同じ扱い)。"""
    thr = fc["metadata"]["counts"]["overlap_km"]
    for key, other in (("overlap_with_ksj", p12), ("overlap_with_wikidata", wd)):
        pts = [f["geometry"]["coordinates"] for f in other["features"]]
        near = sum(
            1 for f in fc["features"]
            if any(haversine_km(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
                                p[0], p[1]) <= thr for p in pts)
        )
        assert near == fc["metadata"]["counts"][key], key


def test_ほったらかし温泉がどこかの層に出る(fc, p12, wd):
    """この層を足した理由そのもの(利用者の指摘 2026-09-10)。

    Q11277778 は instance of が 日帰り入浴施設 で、上位クラスを辿っても
    温泉(Q177380)に当たらない。だから温泉の 2 層には入らない。
    **入浴施設の層には入っていること**を固定する。
    """
    fac = [f for f in fc["features"] if f["properties"]["wikidata_id"] == "Q11277778"]
    assert len(fac) == 1, "ほったらかし温泉(Q11277778)が入浴施設の層に無い"
    assert fac[0]["properties"]["name"] == "ほったらかし温泉"
    assert "入浴施設" in (fac[0]["properties"]["facility_class"] or "")
    # 温泉の 2 層には入っていない(混ぜていないことの確認)
    names = [f["properties"].get("name") for f in p12["features"] + wd["features"]]
    assert "ほったらかし温泉" not in names


def test_統計はこの層を使っていない():
    """対照群は P12 の中から取っている。出所の違う点を混ぜると揃えが壊れる。"""
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    assert stats["generated_from"]["onsen"] == len(onsen["features"])
    for f in onsen["features"]:
        assert f["properties"].get("provenance", "ksj-p12") != "wikidata-facility"


def test_銭湯が含まれることを隠していない(fc):
    """この層の性格。温泉でないものが実際に入っていることを、数で確かめる。

    「温泉とは限らない」と画面に書いている以上、実際にそうであること
    (= 温泉でない分類が実在すること)を検査で押さえる。
    """
    classes = fc["metadata"]["classes"]
    assert sum(classes.values()) == len(fc["features"])
    non_onsen = sum(v for k, v in classes.items() if "銭湯" in k or "公衆浴場" in k)
    assert non_onsen > 0, "銭湯・公衆浴場が 1 件も無いなら、この注意書きは要らない"
