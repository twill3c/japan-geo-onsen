"""Wikidata の温泉を第二の点レイヤーにする。

## なぜ足すのか

環境省は温泉地を **2,839** と数えているが(SPEC §6)、その一覧は公開されていない。
集計 PDF に載っているのは数だけである。一方こちらの地図は国土数値情報 P12 から
採った **1,320 点**しか持っておらず、10 都府県には 1 点も無い。

Wikidata には座標つきの日本の温泉が **1,477 件**あり、ライセンスは CC0 なので
政府データと混ぜても利用条件が濁らない。重ねると地図の被覆が広がる。

## ただし性格が違う

P12 は行政が集めた資料の統合である。Wikidata は**記事が書かれた温泉が載っている**
データで、悉皆調査ではない。だから

- 出所を `provenance` に必ず持たせ、P12 の点と**別のレイヤー**にする
- **統計(温泉と地理環境)には使わない。** あちらの対照群は「同じ P12 の温泉以外の点」で、
  出所を揃えることで「人が登録した場所」という偏りを打ち消している。
  出所の違う点を混ぜるとその揃えが崩れる
- 重なりは**消さない**。出所が違うので両方残し、重なりの数だけを記録する

出典: Wikidata(CC0) https://www.wikidata.org/
クエリ: instance of / subclass of 温泉(Q177380)、国 = 日本(Q17)、座標(P625)を持つもの
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_onsen_base import UNAVAILABLE
from etl.common import DATA, RAW, haversine_km, write_json

RAW_QUERY = RAW / "wikidata" / "onsen_query_result.json"
OUT = DATA / "onsen_wikidata.geojson"

# 日本の範囲。P12 側の検査と同じ枠を使う
JAPAN_BBOX = (122.0, 20.0, 154.0, 46.0)

# P12 の点とどれだけ近ければ「同じ場所を指している」とみなすか。
# 消すためではなく、重なりの数を記録するための閾値
OVERLAP_KM = 0.3

SPARQL = """
SELECT ?x ?xLabel ?coord WHERE {
  ?x wdt:P31/wdt:P279* wd:Q177380 .
  ?x wdt:P17 wd:Q17 .
  ?x wdt:P625 ?coord .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""


def fetch_raw() -> list[dict]:
    """Wikidata に問い合わせて raw に保存する。既にあれば触らない。"""
    if RAW_QUERY.exists():
        return json.loads(RAW_QUERY.read_text(encoding="utf-8"))
    import urllib.parse
    import urllib.request

    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": SPARQL, "format": "json"}
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "japan-geo-onsen/0.1 (educational GIS project)",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        doc = json.load(r)
    rows = []
    for b in doc["results"]["bindings"]:
        lon, lat = b["coord"]["value"].replace("Point(", "").replace(")", "").split()
        rows.append({
            "qid": b["x"]["value"].rsplit("/", 1)[-1],
            "name": b["xLabel"]["value"],
            "lon": float(lon),
            "lat": float(lat),
        })
    RAW_QUERY.parent.mkdir(parents=True, exist_ok=True)
    write_json(RAW_QUERY, rows)
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    """同じ項目に座標が複数ある行を畳む(最初のものを採る)。

    畳まずに出すと同じ温泉に点が重なり、数を水増しする
    (実測 2026-09-08: 行 2,338 に対し項目 1,477)。
    """
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(r["qid"], r)
    return list(seen.values())


def clean_name(qid: str, label: str) -> str | None:
    """ラベルが Q 番号のままの項目は名前が無いものとして扱う。

    そのまま出すと地図に「Q12345」と表示される。名前を作らず null にする。
    """
    if label == qid or (label.startswith("Q") and label[1:].isdigit()):
        return None
    return label


def build() -> dict:
    rows = dedupe(fetch_raw())
    w, s, e, n = JAPAN_BBOX
    inside = [r for r in rows if w <= r["lon"] <= e and s <= r["lat"] <= n]
    outside = len(rows) - len(inside)

    features = []
    unnamed = 0
    for r in sorted(inside, key=lambda x: int(x["qid"][1:])):
        name = clean_name(r["qid"], r["name"])
        if name is None:
            unnamed += 1
        props = {
            "onsen_id": f"wd-{r['qid']}",
            "wikidata_id": r["qid"],
            "provenance": "wikidata",
            "name": name,
            "name_has_onsen": bool(name and ("温泉" in name or "湯" in name)),
        }
        props.update({k: None for k in UNAVAILABLE})
        features.append({
            "type": "Feature",
            "id": props["onsen_id"],
            "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]},
            "properties": props,
        })

    # P12 との重なりを数える(消さない)
    p12 = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    pts = [f["geometry"]["coordinates"] for f in p12["features"]]
    near = 0
    for f in features:
        lon, lat = f["geometry"]["coordinates"]
        if any(haversine_km(lon, lat, p[0], p[1]) <= OVERLAP_KM for p in pts):
            near += 1

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "Wikidata",
            "dataset": "日本の温泉(instance of / subclass of 温泉 Q177380・国 = 日本・座標あり)",
            "source_url": "https://query.wikidata.org/",
            "license": "CC0 1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "download_date": "2026-09-08",
            "sparql": SPARQL.strip(),
            "processing_method": (
                "同じ項目に複数ある座標を畳み、日本の範囲に入るものだけを採った。"
                "ラベルが Q 番号のままの項目は名前を作らず null にした。"
                "P12 の点と重なるものも**消していない**(出所が違うので両方残す)"
            ),
            "caution": (
                "悉皆調査ではなく「記事が書かれた温泉が載っている」データである。"
                "統計(温泉と地理環境)には使わない —— 対照群と出所が揃わなくなるため"
            ),
            "counts": {
                "raw_rows": len(fetch_raw()),
                "distinct_items": len(rows),
                "outside_japan": outside,
                "extracted": len(features),
                "unnamed": unnamed,
                "name_has_onsen": sum(1 for f in features if f["properties"]["name_has_onsen"]),
            },
            "overlap": {
                "threshold_km": OVERLAP_KM,
                "p12_points": len(pts),
                "within_threshold": near,
                "new_locations": len(features) - near,
                "distinct_locations": len(pts) + len(features) - near,
            },
            "unavailable_fields": list(UNAVAILABLE),
        },
    }


if __name__ == "__main__":
    fc = build()
    write_json(OUT, fc)
    c = fc["metadata"]["counts"]
    o = fc["metadata"]["overlap"]
    print(f"{OUT}: {c['extracted']} 点")
    print(f"  生データ 行 {c['raw_rows']} → 項目 {c['distinct_items']}"
          f"(日本の外 {c['outside_japan']})・名前なし {c['unnamed']}")
    print(f"  P12 {o['p12_points']} 点と {o['threshold_km']} km 以内で重なる {o['within_threshold']} 件 "
          f"→ 新しい場所 {o['new_locations']}")
    print(f"  重複を除いた地点の数 {o['distinct_locations']}")
