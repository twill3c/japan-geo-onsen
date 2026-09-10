"""Wikipedia の温泉記事から作った第四の層と、未掲載一覧の検算(SPEC G-18)。

この層は**出所も利用条件も他と違う**(CC BY-SA 4.0)。さらに、都道府県の温泉カテゴリには
温泉のある施設も入る。だから

- 出所と記事への経路(URL)を必ず持ち、他の層と混ざらないこと
- 座標がどこから来たか(記事 / Wikidata)を点ごとに持つこと
- 統計には使わないこと
- **座標が無くて出せなかったものが、一覧に漏れなく載っていること**

を検査で固定する。件数は raw の実物から数え直す(定数で書かない)。

利用者の指摘(山中湖温泉・大田区の黒湯温泉)そのものも検査に落とす。
「なぜ出せないか」を文章にだけ書くと、次の変更で静かに消える。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_onsen_base import UNAVAILABLE
from etl.build_onsen_wikipedia import JAPAN_BBOX, RAW_SNAPSHOT
from etl.common import DATA

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def raw():
    return json.loads(RAW_SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fc():
    return json.loads((DATA / "onsen_wikipedia.geojson").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def missing():
    return json.loads((DATA / "onsen_missing.json").read_text(encoding="utf-8"))


def test_点の数が生データと一致する(raw, fc):
    w, s, e, n = JAPAN_BBOX
    have = [r for r in raw["rows"] if r["lat"] is not None
            and w <= r["lon"] <= e and s <= r["lat"] <= n]
    assert len(fc["features"]) == len(have)
    c = fc["metadata"]["counts"]
    assert c["articles"] == len(raw["rows"])
    assert c["with_coordinates"] == sum(1 for r in raw["rows"] if r["lat"] is not None)
    assert c["without_coordinates"] == sum(1 for r in raw["rows"] if r["lat"] is None)
    assert c["with_coordinates"] + c["without_coordinates"] == c["articles"]


def test_全点が出所と記事への経路を持つ(fc):
    for f in fc["features"]:
        p = f["properties"]
        assert p["provenance"] == "wikipedia"
        assert p["onsen_id"].startswith("wp-")
        assert p["wikipedia_url"].startswith("https://ja.wikipedia.org/wiki/")
        assert p["coord_source"] in ("wikipedia", "wikidata")


def test_座標の出どころの内訳が記録と合う(fc):
    c = fc["metadata"]["counts"]
    got = {"wikipedia": 0, "wikidata": 0}
    for f in fc["features"]:
        got[f["properties"]["coord_source"]] += 1
    # 日本の外を落としているので、出荷点の合計と一致すること
    assert got["wikipedia"] + got["wikidata"] == len(fc["features"])
    assert c["coord_from_wikipedia"] >= got["wikipedia"]


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


def test_統計はこの層を使っていない():
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    assert stats["generated_from"]["onsen"] == len(onsen["features"])
    for f in onsen["features"]:
        assert f["properties"].get("provenance", "ksj-p12") != "wikipedia"


def test_一覧と地図が排他(fc, missing):
    """同じ記事が「点」と「出せないもの」の両方に載ってはならない。"""
    on_map = {f["properties"]["name"] for f in fc["features"]}
    listed = {r["name"] for r in missing["wikipedia"]}
    assert not (on_map & listed), sorted(on_map & listed)[:5]


def test_座標の無い記事が漏れなく一覧に載る(raw, missing):
    none = {r["title"] for r in raw["rows"] if r["lat"] is None}
    assert {r["name"] for r in missing["wikipedia"]} == none


def test_指摘された温泉が一覧に載っている(missing):
    """利用者の指摘そのもの(2026-09-10)。

    - 大田区の黒湯温泉(Q671405): 分類は「温泉」で条件に合うが座標が無い
    - 山中湖温泉(Q108702377): 項目は在るが座標が無く、記事とも紐付いていない
      (記事側から辿ると「項目なし」に見える)
    """
    qids = {r["wikidata_id"] for r in missing["wikidata"]}
    assert "Q671405" in qids, "大田区の黒湯温泉が一覧に無い"
    assert "Q108702377" in qids, "山中湖温泉が一覧に無い"
    names = {r["name"] for r in missing["wikipedia"]}
    assert "山中湖温泉" in names
    assert "大田区の黒湯温泉" in names


def test_一覧にまとまりや概念が混ざることを隠していない(missing):
    """「432 件の温泉が出せない」と読ませないための検査。

    温泉郷のようなまとまりが実在することを、分類の内訳から確かめる。
    """
    classes = missing["wikidata_classes"]
    assert sum(classes.values()) >= len(missing["wikidata"])
    assert classes.get("温泉郷", 0) > 0, "まとまりが 1 件も無いなら、この注意書きは要らない"
    for r in missing["wikidata"]:
        assert "classes" in r


def test_一覧の出所と件数が本文と合う(missing):
    counts = {s["source"]: s["count"] for s in missing["sources"]}
    assert counts["日本語版 Wikipedia"] == len(missing["wikipedia"])
    assert counts["Wikidata"] == len(missing["wikidata"])
