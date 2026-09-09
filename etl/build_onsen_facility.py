"""Wikidata で「入浴施設」に分類されている場所を、第三の点レイヤーにする。

## なぜ足すのか

利用者から「ほったらかし温泉が地図に無い」と指摘があった。調べると、

- **国土数値情報 P12(2014)には 1 件も無い。** 全国 17,258 点を名前で探して 0 件。
  抽出規則で落としたのではなく、台帳に載っていない
- **Wikidata には項目が在る**(Q11277778・座標 138.652222/35.706111・所在地 山梨市)。
  しかし `instance of` が **日帰り入浴施設(Q11505291)** で、上位クラスを 33 件辿っても
  **温泉(Q177380) に当たらない**。だから既存の Wikidata 層のクエリに掛からない

同じ理由で漏れる項目は、日本・座標あり・入浴施設(Q17521458)系で **107 件**、
うち名前に「温泉」を含むか「湯」で終わるものが **77 件**あった(実測 2026-09-10)。

## なぜ温泉の層に混ぜないのか

**入浴施設は温泉とは限らない。** 銭湯・公衆浴場も同じクラスに入る。
既存の 2 層(P12・Wikidata の温泉)に混ぜると「温泉の点」という層の意味が濁る。
出所と分類が違うものは**層を分ける**——これはこの地図の一貫した扱いである。

したがってこの層も、

- `provenance` を持たせ、地図では別の色・別の切替にする
- **統計(温泉と地理環境)には使わない。** 対照群は P12 の中から選んでおり、
  出所を揃えることで偏りを打ち消しているので、混ぜるとその揃えが壊れる
- 既存 2 層との重なりは**消さない**。数えるだけにする

出典: Wikidata(CC0) https://www.wikidata.org/
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_onsen_base import UNAVAILABLE
from etl.common import DATA, RAW, UA, haversine_km, write_json

RAW_QUERY = RAW / "wikidata" / "facility_query_result.json"
OUT = DATA / "onsen_facility.geojson"

# 日本の範囲。温泉の層と同じ枠を使う
JAPAN_BBOX = (122.0, 20.0, 154.0, 46.5)
OVERLAP_KM = 0.3

# Q17521458 = 入浴施設。日帰り入浴施設・公衆浴場はこの下位にある。
# Q177380 = 温泉。**既に別の層で採っているものは除く**(二重に出さない)。
SPARQL = """
SELECT ?x ?xLabel ?cls ?clsLabel ?coord WHERE {
  ?x wdt:P31/wdt:P279* wd:Q17521458 .
  ?x wdt:P17 wd:Q17 .
  ?x wdt:P625 ?coord .
  ?x wdt:P31 ?cls .
  FILTER NOT EXISTS { ?x wdt:P31/wdt:P279* wd:Q177380 . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""


def fetch_raw() -> list[dict]:
    """Wikidata に問い合わせて raw に保存する。既にあれば触らない。"""
    if RAW_QUERY.exists():
        return json.loads(RAW_QUERY.read_text(encoding="utf-8"))
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": SPARQL, "format": "json"})
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        doc = json.load(r)
    rows = []
    for b in doc["results"]["bindings"]:
        lon, lat = b["coord"]["value"].replace("Point(", "").replace(")", "").split()
        rows.append({
            "qid": b["x"]["value"].rsplit("/", 1)[-1],
            "name": b["xLabel"]["value"],
            "class": b.get("clsLabel", {}).get("value", ""),
            "lon": float(lon),
            "lat": float(lat),
        })
    RAW_QUERY.parent.mkdir(parents=True, exist_ok=True)
    write_json(RAW_QUERY, rows)
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    """同じ項目の複数行(座標や分類が複数ある)を畳む。分類は集めて残す。"""
    seen: dict[str, dict] = {}
    for r in rows:
        cur = seen.get(r["qid"])
        if cur is None:
            seen[r["qid"]] = {**r, "classes": [r["class"]] if r["class"] else []}
            continue
        if r["class"] and r["class"] not in cur["classes"]:
            cur["classes"].append(r["class"])
    return list(seen.values())


def clean_name(qid: str, label: str) -> str | None:
    """ラベルが Q 番号のままの項目は名前が無いものとして扱う。"""
    if label == qid or (label.startswith("Q") and label[1:].isdigit()):
        return None
    return label


def build() -> dict:
    raw_rows = fetch_raw()
    rows = dedupe(raw_rows)
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
            "onsen_id": f"wdf-{r['qid']}",
            "wikidata_id": r["qid"],
            "provenance": "wikidata-facility",
            "name": name,
            # 「温泉」を名に持つかどうかは**利用者が絞り込むための印**であって、
            # 温泉であることの証明ではない
            "name_has_onsen": bool(name and ("温泉" in name or name.endswith("湯"))),
            "facility_class": "・".join(r["classes"]) or None,
        }
        props.update({k: None for k in UNAVAILABLE})
        features.append({
            "type": "Feature",
            "id": props["onsen_id"],
            "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]},
            "properties": props,
        })

    # 既存 2 層との重なりを数える(消さない)
    overlaps = {}
    for path, key in (("onsen.geojson", "ksj"), ("onsen_wikidata.geojson", "wikidata")):
        pts = [f["geometry"]["coordinates"]
               for f in json.loads((DATA / path).read_text(encoding="utf-8"))["features"]]
        overlaps[key] = sum(
            1 for f in features
            if any(haversine_km(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
                                p[0], p[1]) <= OVERLAP_KM for p in pts)
        )

    classes: dict[str, int] = {}
    for f in features:
        classes[f["properties"]["facility_class"] or "(分類なし)"] = \
            classes.get(f["properties"]["facility_class"] or "(分類なし)", 0) + 1

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "Wikidata",
            "dataset": ("日本の入浴施設(instance of / subclass of 入浴施設 Q17521458・国 = 日本・"
                        "座標あり。**温泉 Q177380 に当たるものは除く**——そちらは別の層にある)"),
            "source_url": "https://query.wikidata.org/",
            "license": "CC0 1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "download_date": "2026-09-10",
            "sparql": SPARQL.strip(),
            "processing_method": (
                "同じ項目の複数行を畳み(分類は集めて残す)、日本の範囲に入るものだけを採った。"
                "ラベルが Q 番号のままの項目は名前を作らず null にした。"
                "既存 2 層と重なるものも消していない(出所が違うので両方残す)"
            ),
            "caution": (
                "**入浴施設は温泉とは限らない。** 銭湯・公衆浴場も同じクラスに入る。"
                "この層は『Wikidata が入浴施設として登録している場所』であって、"
                "温泉であることの証明ではない。"
                "統計(温泉と地理環境)には使わない —— 対照群と出所が揃わなくなるため"
            ),
            "why": (
                "P12 にも Wikidata の温泉クラスにも入らない入浴施設がある。"
                "例: ほったらかし温泉(Q11277778)は instance of が 日帰り入浴施設で、"
                "上位クラスを辿っても温泉に当たらない"
            ),
            "counts": {
                "raw_rows": len(raw_rows),
                "distinct_items": len(rows),
                "outside_japan": outside,
                "extracted": len(features),
                "unnamed": unnamed,
                "name_has_onsen": sum(1 for f in features if f["properties"]["name_has_onsen"]),
                "overlap_with_ksj": overlaps["ksj"],
                "overlap_with_wikidata": overlaps["wikidata"],
                "overlap_km": OVERLAP_KM,
            },
            "classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
        },
    }


if __name__ == "__main__":
    doc = build()
    write_json(OUT, doc)
    c = doc["metadata"]["counts"]
    print(f"{OUT}: {c['extracted']} 点(項目 {c['distinct_items']} / 行 {c['raw_rows']})")
    print(f"  名前に温泉/湯 {c['name_has_onsen']} / 名前なし {c['unnamed']} / "
          f"日本の外 {c['outside_japan']}")
    print(f"  重なり: P12 と {c['overlap_with_ksj']} / Wikidata 温泉と {c['overlap_with_wikidata']}")
    for k, v in list(doc["metadata"]["classes"].items())[:8]:
        print(f"  {k}: {v}")
