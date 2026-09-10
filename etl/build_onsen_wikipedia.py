"""日本語版 Wikipedia の温泉記事を第四の点レイヤーにし、**載せられないもの**を一覧にする。

## なぜ足すのか

利用者から「山中湖温泉・大田区の黒湯温泉が地図に無い。Wikipedia から辿れないか」と
指摘があった。辿れるかを実測したところ(etl/probe_wikipedia_onsen.py)、

- 47 都道府県の「○○の温泉」カテゴリ直下の記事は **1,862 件**
- そのうち座標があるのは **1,344 件**(記事の {{coord}} 1,152 / Wikidata 192)
- 既存 3 層(2,905 点)から 300 m 以上離れた**新しい場所は 174 件**で、
  **うち 165 件は記事にしか座標が無い** —— Wikidata だけ見ていては取れない
- **座標がどこにも無い記事が 518 件**。指摘された 2 件はどちらもここに入る

つまり「辿れば増える」が「辿れば全部載る」ではない。**載らないものを数と名前で言う**
ために、座標の無いものを一覧として別に出す(設計書 §72 の精神)。

## この層の性格(混ぜない理由)

- 出所が **CC BY-SA 4.0**。既存(CC0・政府の利用約款)と条件が違うので出典表示を別に立てる
- 都道府県の温泉カテゴリには**温泉のある施設**も入る(遊園地・公園・国民宿舎・
  パーキングエリアなど)。Wikidata の分類が引ける場合は属性として持たせる
- 座標の精度はまちまち。温泉街の中心を指すものも、建物を指すものもある
- **統計(温泉と地理環境)には使わない。** 対照群は P12 の中から取っている

出典: 日本語版 Wikipedia(CC BY-SA 4.0) https://ja.wikipedia.org/
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
from etl.probe_wikipedia_onsen import (
    ROOTS, article_info, collect_articles, wikidata_coords,
)

RAW_SNAPSHOT = RAW / "wikipedia" / "onsen_articles.json"
OUT = DATA / "onsen_wikipedia.geojson"
OUT_MISSING = DATA / "onsen_missing.json"

JAPAN_BBOX = (122.0, 20.0, 154.0, 46.5)
OVERLAP_KM = 0.3

LICENSE = {
    "source": "日本語版 Wikipedia",
    "dataset": "47 都道府県の「○○の温泉」カテゴリ直下の記事(記事名前空間のみ)",
    "source_url": "https://ja.wikipedia.org/",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.ja",
    "download_date": "2026-09-10",
}


def fetch() -> dict:
    """記事名・座標・Wikidata の ID を取ってきて raw に置く。既にあれば触らない。"""
    if RAW_SNAPSHOT.exists():
        return json.loads(RAW_SNAPSHOT.read_text(encoding="utf-8"))

    articles, cats = collect_articles()
    info = article_info(articles)
    need = [v["qid"] for v in info.values() if v["lat"] is None and v["qid"]]
    wd = wikidata_coords(need) if need else {}

    rows = []
    for title, v in info.items():
        lon, lat, src = v["lon"], v["lat"], "wikipedia"
        if lat is None and v["qid"] in wd:
            lon, lat = wd[v["qid"]]
            src = "wikidata"
        rows.append({"title": title, "qid": v["qid"], "lon": lon, "lat": lat,
                     "coord_source": src if lat is not None else None})
    doc = {"categories": cats, "rows": sorted(rows, key=lambda r: r["title"])}
    RAW_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    write_json(RAW_SNAPSHOT, doc, indent=1)
    return doc


def wikidata_classes(qids: list[str]) -> dict[str, list[str]]:
    """Wikidata の分類(instance of)。引けないものは空。"""
    out: dict[str, list[str]] = {}
    for i in range(0, len(qids), 200):
        values = " ".join(f"wd:{q}" for q in qids[i:i + 200])
        q = (f"SELECT ?x ?cLabel WHERE {{ VALUES ?x {{ {values} }} ?x wdt:P31 ?c . "
             f'SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en". }} }}')
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
            {"query": q, "format": "json"})
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            rows = json.load(r)["results"]["bindings"]
        for b in rows:
            qid = b["x"]["value"].rsplit("/", 1)[-1]
            label = b.get("cLabel", {}).get("value", "")
            if label and label not in out.setdefault(qid, []):
                out[qid].append(label)
    return out


def missing_from_wikidata() -> list[dict]:
    """Wikidata で『日本の温泉』だが座標が無い項目。地図に出せないもう一つの集団。

    **分類(instance of)も一緒に採る。** この集団には個々の温泉だけでなく、
    温泉郷・八湯のような**まとまり**や、「名湯百選」「日本三古湯」のような**概念**、
    閉業した施設も混ざる(実測)。分類を見せずに名前だけ並べると、
    「地図に出せない温泉が 432 件ある」と読めてしまう。
    """
    q = """
SELECT ?x ?xLabel ?adminLabel ?clsLabel WHERE {
  ?x wdt:P31/wdt:P279* wd:Q177380 .
  ?x wdt:P17 wd:Q17 .
  OPTIONAL { ?x wdt:P131 ?admin . }
  OPTIONAL { ?x wdt:P31 ?cls . }
  FILTER NOT EXISTS { ?x wdt:P625 ?c . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": q, "format": "json"})
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        rows = json.load(r)["results"]["bindings"]
    seen: dict[str, dict] = {}
    for b in rows:
        qid = b["x"]["value"].rsplit("/", 1)[-1]
        name = b.get("xLabel", {}).get("value", "")
        if name == qid:
            name = ""
        rec = seen.setdefault(qid, {
            "name": name or None,
            "wikidata_id": qid,
            "admin": b.get("adminLabel", {}).get("value"),
            "classes": [],
        })
        cls = b.get("clsLabel", {}).get("value")
        if cls and cls not in rec["classes"]:
            rec["classes"].append(cls)
    return sorted(seen.values(), key=lambda r: (r["name"] or "￿"))


def build() -> tuple[dict, dict]:
    doc = fetch()
    rows = doc["rows"]
    have = [r for r in rows if r["lat"] is not None]
    none = [r for r in rows if r["lat"] is None]

    w, s, e, n = JAPAN_BBOX
    inside = [r for r in have if w <= r["lon"] <= e and s <= r["lat"] <= n]
    outside = len(have) - len(inside)

    classes = wikidata_classes([r["qid"] for r in inside if r["qid"]])

    features = []
    for r in sorted(inside, key=lambda x: x["title"]):
        title = r["title"]
        props = {
            "onsen_id": f"wp-{title}",
            "wikidata_id": r["qid"],
            "provenance": "wikipedia",
            "name": title,
            "name_has_onsen": ("温泉" in title or title.endswith("湯")),
            "coord_source": r["coord_source"],
            "wikipedia_url": "https://ja.wikipedia.org/wiki/" + urllib.parse.quote(title),
            "facility_class": "・".join(classes.get(r["qid"] or "", [])) or None,
        }
        props.update({k: None for k in UNAVAILABLE})
        features.append({
            "type": "Feature",
            "id": props["onsen_id"],
            "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]},
            "properties": props,
        })

    # 既存 3 層との重なりを数える(消さない)
    overlaps = {}
    existing = []
    for path, key in (("onsen.geojson", "ksj"), ("onsen_wikidata.geojson", "wikidata"),
                      ("onsen_facility.geojson", "facility")):
        pts = [f["geometry"]["coordinates"]
               for f in json.loads((DATA / path).read_text(encoding="utf-8"))["features"]]
        existing += pts
        overlaps[key] = sum(
            1 for f in features
            if any(haversine_km(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
                                p[0], p[1]) <= OVERLAP_KM for p in pts)
        )
    new_places = [
        f for f in features
        if not any(haversine_km(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
                                p[0], p[1]) <= OVERLAP_KM for p in existing)
    ]

    fc = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            **LICENSE,
            "root_categories": len(ROOTS),
            "processing_method": (
                "47 都道府県の「○○の温泉」カテゴリの**直下**にある記事(名前空間 0)を集め、"
                "記事の座標を採った。記事に無い場合だけ Wikidata の P625 を見た。"
                "日本の範囲に入るものだけを採り、既存 3 層と重なるものも消していない"
            ),
            "caution": (
                "**都道府県の温泉カテゴリには「温泉のある施設」も入る**"
                "(遊園地・公園・国民宿舎・パーキングエリアなど)。温泉そのものとは限らない。"
                "座標の精度もまちまちで、温泉街の中心を指すものと建物を指すものが混ざる。"
                "統計(温泉と地理環境)には使わない"
            ),
            "counts": {
                "articles": len(rows),
                "with_coordinates": len(have),
                "coord_from_wikipedia": sum(1 for r in have if r["coord_source"] == "wikipedia"),
                "coord_from_wikidata": sum(1 for r in have if r["coord_source"] == "wikidata"),
                "without_coordinates": len(none),
                "outside_japan": outside,
                "extracted": len(features),
                "new_locations": len(new_places),
                "overlap_km": OVERLAP_KM,
                **{f"overlap_with_{k}": v for k, v in overlaps.items()},
            },
        },
    }

    wd_missing = missing_from_wikidata()
    missing = {
        "note": (
            "**名前は分かるが、位置が公開データに無い温泉。**"
            "緯度経度を作れば地図に出せるが、それは架空のデータを作ることになる"
            "(設計書 §71/§72)。だから地図には出さず、ここに名前で残す"
        ),
        "generated_at": LICENSE["download_date"],
        "sources": [
            {**LICENSE, "what": "座標が無い温泉記事", "count": len(none)},
            {"source": "Wikidata", "license": "CC0 1.0",
             "source_url": "https://query.wikidata.org/",
             "what": "instance of/subclass of 温泉・国=日本 だが座標(P625)が無い項目",
             "count": len(wd_missing)},
        ],
        "wikipedia": [
            {"name": r["title"], "wikidata_id": r["qid"],
             "url": "https://ja.wikipedia.org/wiki/" + urllib.parse.quote(r["title"])}
            for r in sorted(none, key=lambda x: x["title"])
        ],
        "wikidata": wd_missing,
        "wikidata_classes": _class_counts(wd_missing),
    }
    return fc, missing


def _class_counts(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        for c in r["classes"] or ["(分類なし)"]:
            out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    fc, missing = build()
    write_json(OUT, fc)
    write_json(OUT_MISSING, missing, indent=1)
    c = fc["metadata"]["counts"]
    print(f"{OUT}: {c['extracted']} 点 / 記事 {c['articles']} 件")
    print(f"  座標あり {c['with_coordinates']}(記事 {c['coord_from_wikipedia']} / "
          f"Wikidata {c['coord_from_wikidata']}) / 座標なし {c['without_coordinates']}")
    print(f"  新しい場所 {c['new_locations']} / 重なり "
          f"P12 {c['overlap_with_ksj']}・Wikidata温泉 {c['overlap_with_wikidata']}・"
          f"入浴施設 {c['overlap_with_facility']}")
    print(f"{OUT_MISSING}: 記事 {len(missing['wikipedia'])} 件 + Wikidata {len(missing['wikidata'])} 件")
