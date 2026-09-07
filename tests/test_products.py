"""出荷する GeoJSON が、生データに 1 対 1 で遡れることを確かめる(SPEC G-01)。

期待値の出所はすべて「raw/ の実物」である。件数は定数で書かず、
**生データ側から数え直したものと一致すること**を言う(HC-016)。
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
from pathlib import Path

import pytest
import shapefile  # pyshp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_onsen_base import CATEGORY_ONSEN_HEALTH, KIND_ONSEN, UNAVAILABLE, clean
from etl.build_volcanoes import JMA_PUBLISHED_ACTIVE_VOLCANOES, classify
from etl.common import DATA, RAW, ensure_p12, haversine_km, vincenty_km

pytestmark = pytest.mark.validation


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def volcanoes() -> dict:
    return load("volcanoes.geojson")


@pytest.fixture(scope="module")
def onsen() -> dict:
    return load("onsen.geojson")


@pytest.fixture(scope="module")
def jma_raw() -> list[dict]:
    return json.loads((RAW / "jma" / "volcano_list.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 火山(G-04)

def test_火山の件数が気象庁の公表値と一致する(volcanoes, jma_raw):
    """出所: 気象庁「活火山とは」(2026-09-07 取得)が公表する 111。

    名簿 120 件の内訳を名簿自身から分解して 111 を得る。分解が崩れたら落ちる。
    """
    vs, subs, pseudo = classify(jma_raw)
    assert len(vs) == JMA_PUBLISHED_ACTIVE_VOLCANOES
    assert len(vs) + len(subs) + len(pseudo) == len(jma_raw)
    assert len(volcanoes["features"]) == len(vs)


def test_火山の全点が名簿の実在項目に遡れる(volcanoes, jma_raw):
    by_code = {e["code"]: e for e in jma_raw}
    for f in volcanoes["features"]:
        code = f["properties"]["volcano_id"]
        assert code in by_code, f"名簿に無い火山番号 {code}"
        src = by_code[code]
        lon, lat = f["geometry"]["coordinates"]
        assert lat == pytest.approx(float(src["latlon"][0]))
        assert lon == pytest.approx(float(src["latlon"][1]))
        assert f["properties"]["name"] == src["name_jp"]


def test_火口の細分は火山として出さない(volcanoes, jma_raw):
    _, subs, _ = classify(jma_raw)
    assert len(subs) > 0, "細分が 0 件なら、この検査は空振りしている"
    names = {f["properties"]["name"] for f in volcanoes["features"]}
    for s in subs:
        assert s["name_jp"] not in names


def test_火口の細分は親火山の属性として残っている(volcanoes, jma_raw):
    _, subs, _ = classify(jma_raw)
    listed = {c for f in volcanoes["features"] for c in f["properties"]["craters"]}
    assert {s["name_jp"] for s in subs} == listed


# ---------------------------------------------------------------- 温泉(G-01/G-03/G-05)

@pytest.fixture(scope="module")
def p12_matches() -> list[dict]:
    """raw の P12 から、採録規則に合う点を数え直す。"""
    ensure_p12()
    out = []
    for path in sorted(glob.glob(str(RAW / "ksj" / "P12" / "P12a-14_*.shp"))):
        reader = shapefile.Reader(path, encoding="cp932")
        names = [f[0] for f in reader.fields[1:]]
        for sr in reader.iterShapeRecords():
            rec = dict(zip(names, sr.record))
            kind, code = clean(rec["P12_005"]), clean(rec["P12_007"])
            if kind == KIND_ONSEN or code == CATEGORY_ONSEN_HEALTH:
                out.append({
                    "source_id": clean(rec["P12_001"]),
                    "pref": clean(rec["P12_003"]),
                    "name": clean(rec["P12_002"]),
                    "lonlat": sr.shape.points[0],
                })
    return out


def test_温泉点は生データと同数で取りこぼしが無い(onsen, p12_matches):
    assert len(onsen["features"]) == len(p12_matches)
    got = sorted((f["properties"]["source_id"], f["properties"]["prefecture_code"],
                  f["properties"]["name"]) for f in onsen["features"])
    want = sorted((m["source_id"], m["pref"], m["name"]) for m in p12_matches)
    assert got == want


def test_温泉点の座標が生データと一致する(onsen, p12_matches):
    """同じ ID が重複しうるので、座標の多重集合で突き合わせる。"""
    got = sorted((round(f["geometry"]["coordinates"][0], 6),
                  round(f["geometry"]["coordinates"][1], 6)) for f in onsen["features"])
    want = sorted((round(m["lonlat"][0], 6), round(m["lonlat"][1], 6)) for m in p12_matches)
    assert got == want


def test_ID_は一意である(onsen):
    ids = [f["properties"]["onsen_id"] for f in onsen["features"]]
    assert len(ids) == len(set(ids))


def test_重複した元IDは畳まずに残っている(onsen, p12_matches):
    """出所: 実測 2026-09-07。秋田県 10297 が座標違いで 2 レコードある。

    「重複していた」こと自体が消えていないかを見る(HC-201)。
    """
    from collections import Counter
    raw_dup = [k for k, n in Counter((m["source_id"], m["pref"]) for m in p12_matches).items() if n > 1]
    assert raw_dup, "生データ側に重複が無いなら、この検査は空振りしている"
    for sid, pref in raw_dup:
        kept = [f for f in onsen["features"]
                if f["properties"]["source_id"] == sid and f["properties"]["prefecture_code"] == pref]
        assert len(kept) == Counter((m["source_id"], m["pref"]) for m in p12_matches)[(sid, pref)]
        assert len({f["properties"]["onsen_id"] for f in kept}) == len(kept)


def test_公開データに無い項目は空のまま出荷される(onsen):
    """SPEC G-03。値を作っていないことを、全点について言う。"""
    assert UNAVAILABLE, "対象の項目が空なら、この検査は空振りしている"
    for f in onsen["features"]:
        for key in UNAVAILABLE:
            assert key in f["properties"], f"{key} の欄そのものが無い"
            assert f["properties"][key] is None, f"{key} に値が入っている"


def test_被覆の穴が実測と一致する(onsen):
    """SPEC G-05。0 件の都道府県をメタデータの記述と実際の点から数え直して突き合わせる。"""
    counts: dict[str, int] = {}
    for f in onsen["features"]:
        p = f["properties"]["prefecture_code"]
        counts[p] = counts.get(p, 0) + 1
    empty = [f"{i:02d}" for i in range(1, 48) if counts.get(f"{i:02d}", 0) == 0]
    assert empty == onsen["metadata"]["counts"]["prefectures_with_zero"]
    assert len(empty) > 0, "穴が無いなら、被覆の注意書きの方を直す"


def test_全点が日本の範囲に収まる(onsen, volcanoes):
    for fc in (onsen, volcanoes):
        for f in fc["features"]:
            lon, lat = f["geometry"]["coordinates"]
            assert 122 <= lon <= 154, f"経度が範囲外: {lon}"
            assert 20 <= lat <= 46, f"緯度が範囲外: {lat}"


# ---------------------------------------------------------------- 距離(G-08)

def test_火山距離が二つの実装で一致する(onsen, volcanoes):
    """SPEC G-08。球面(haversine)と WGS84 測地線(Vincenty)で 0.5% 以内。"""
    vs = [(f["properties"]["name"], *f["geometry"]["coordinates"]) for f in volcanoes["features"]]
    worst = 0.0
    checked = 0
    for f in onsen["features"]:
        d = f["properties"].get("distance_to_volcano_km")
        if d is None:
            continue
        lon, lat = f["geometry"]["coordinates"]
        name = f["properties"]["nearest_volcano"]
        vlon, vlat = next((v[1], v[2]) for v in vs if v[0] == name)
        # 出荷した値が haversine の再計算と一致すること
        assert d == pytest.approx(haversine_km(lon, lat, vlon, vlat), abs=0.01)
        dv = vincenty_km(lon, lat, vlon, vlat)
        if dv > 1.0:
            worst = max(worst, abs(d - dv) / dv)
        checked += 1
    assert checked > 1000, f"照合した点が {checked} 件しかない"
    assert worst < 0.005, f"二実装の相対差が {worst:.5f}"


def test_最寄り火山が本当に最寄りである(onsen, volcanoes):
    vs = [(f["properties"]["name"], *f["geometry"]["coordinates"]) for f in volcanoes["features"]]
    for f in onsen["features"]:
        if f["properties"].get("nearest_volcano") is None:
            continue
        lon, lat = f["geometry"]["coordinates"]
        best = min(haversine_km(lon, lat, v[1], v[2]) for v in vs)
        assert f["properties"]["distance_to_volcano_km"] == pytest.approx(best, abs=0.01)


# ---------------------------------------------------------------- 字種(G-07)

def test_日本語本文に別字種や制御文字が混入していない():
    r = subprocess.run(
        [sys.executable, "harness/text_hygiene.py"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
