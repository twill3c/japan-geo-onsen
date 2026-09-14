"""地域を「基準点 + 半径」で定め、温泉と地理環境を並べる(設計書 §58「地域比較」)。

## 境界を描かない

設計書は「八ヶ岳・富士山・箱根・草津・別府などを比較する」と地名を挙げるだけで、
地域の境界を定めていない。境界を推測で引くと、どこまでを「箱根」と呼ぶかで数がいくらでも
変わる。そこで**基準点から半径 10 km / 25 km の円**を地域にする。

## 基準点の決め方(実測 2026-09-14)

- 設計書の 5 地域は、設計書の語に合う **Wikidata の項目**を基準点にする。
  名前だけで引くと同名の別物が混ざる(「富士山」は茨城 152 m・栃木 160 m の山も在る)ので、
  **分類でちょうど 1 つに絞れなければ止める**
- 気象庁の活火山 111 には「八ヶ岳」が無い(北の「横岳」だけ)。横岳は Wikidata の八ヶ岳から
  約 14 km 北で、そこを基準にすると赤岳・野辺山側が円から外れる。だから山脈の項目を使い、
  **最寄りの活火山とその距離を併記**して、基準点が火山からどれだけ離れているかを隠さない
- 利用者が足せるよう、**気象庁の活火山 111 もそれぞれ基準点にした地域**を作る

## 数え方

- 点の数は出所(4 層)ごとに別に数え、**足さない**(同じ温泉が複数の出所に載る)
- 温泉の要約(標高・河川距離・地質)は**国土数値情報 P12 の点だけ**で取る(出所を混ぜない)
- 湖沼は面の縁まで、植生はメッシュ中心が円に入るもの(周辺環境分析と同じ規則・同じ関数)
- 円の数え方の近道は tests/test_surroundings.py(G-19)で総当たりと一致を確かめてある
"""
from __future__ import annotations

import collections
import json
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_stats import _sizendo_band
from etl.build_surroundings import (
    BANDS, MeshIndex, PointGrid, _box, lake_bounds, lake_distance_km, load_lakes,
)
from etl.build_vegetation import load_mesh, load_tables
from etl.common import DATA, RAW, UA, haversine_km, write_json

RADII_KM = (10, 25)
OUT = DATA / "regions.json"
RAW_ANCHORS = RAW / "wikidata" / "region_anchors.json"

LAYERS = {
    "ksj": "onsen.geojson",
    "wikidata": "onsen_wikidata.geojson",
    "facility": "onsen_facility.geojson",
    "wikipedia": "onsen_wikipedia.geojson",
}

# 設計書 §58 の語 → Wikidata の名前と、同名の別物を落とすための分類(ラベルに含まれる語)
SPEC_REGIONS = [
    {"label": "八ヶ岳", "wikidata_label": "八ヶ岳", "class_any": ["火山群", "山脈"]},
    {"label": "富士山", "wikidata_label": "富士山", "class_any": ["活火山"]},
    {"label": "箱根", "wikidata_label": "箱根温泉", "class_any": ["温泉"]},
    {"label": "草津", "wikidata_label": "草津温泉", "class_any": ["温泉"]},
    {"label": "別府", "wikidata_label": "別府温泉", "class_any": ["温泉"]},
]

COVERAGE_NOTE = "観光資源データ(P12)に点が無い(被覆の穴の可能性)"
# 最初は「P12 が 0 のときだけ」注記していたが、別府は半径 25 km に P12 が 3 点・Wikidata が 22 点で、
# 3 点で中央値と割合を出していた。0 だけを見る規則はこれを見逃す
SMALL_N = 5
SMALL_N_NOTE = f"P12 の点が {SMALL_N} つ未満(要約は参考程度)"


def fetch_anchor_rows() -> list[dict]:
    """基準点の候補を Wikidata から取る。既に取ってあれば触らない。"""
    if RAW_ANCHORS.exists():
        return json.loads(RAW_ANCHORS.read_text(encoding="utf-8"))
    names = " ".join(f'"{r["wikidata_label"]}"@ja' for r in SPEC_REGIONS)
    q = f"""
SELECT ?x ?name ?c ?cLabel ?coord WHERE {{
  VALUES ?name {{ {names} }}
  ?x rdfs:label ?name .
  ?x wdt:P17 wd:Q17 .
  ?x wdt:P625 ?coord .
  OPTIONAL {{ ?x wdt:P31 ?c . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en". }}
}}
"""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        bindings = json.load(r)["results"]["bindings"]
    rows = []
    for b in bindings:
        lon, lat = b["coord"]["value"].replace("Point(", "").replace(")", "").split()
        rows.append({
            "qid": b["x"]["value"].rsplit("/", 1)[-1],
            "name": b["name"]["value"],
            "class_qid": b.get("c", {}).get("value", "").rsplit("/", 1)[-1] or None,
            "class_label": b.get("cLabel", {}).get("value"),
            "lon": float(lon),
            "lat": float(lat),
        })
    RAW_ANCHORS.parent.mkdir(parents=True, exist_ok=True)
    write_json(RAW_ANCHORS, rows, indent=1)
    return rows


def resolve_spec_anchors() -> list[dict]:
    """設計書の語ごとに基準点を**ちょうど 1 つ**決める。決まらなければ止める。"""
    rows = fetch_anchor_rows()
    out = []
    for spec in SPEC_REGIONS:
        cands: dict[str, dict] = {}
        for r in rows:
            if r["name"] != spec["wikidata_label"]:
                continue
            c = cands.setdefault(r["qid"], {**r, "classes": set()})
            if r["class_label"]:
                c["classes"].add(r["class_label"])
        hit = [c for c in cands.values() if c["classes"] & set(spec["class_any"])]
        if len(hit) != 1:
            raise SystemExit(
                f"{spec['label']}: 基準点が 1 つに決まらない "
                f"{[(c['qid'], sorted(c['classes'])) for c in cands.values()]}"
            )
        h = hit[0]
        out.append({
            "label": spec["label"],
            "wikidata_id": h["qid"],
            "wikidata_label": spec["wikidata_label"],
            "classes": sorted(h["classes"]),
            "lon": h["lon"],
            "lat": h["lat"],
        })
    return out


def coverage_note(points: dict[str, int]) -> str | None:
    """P12 の点の少なさを注記する。

    - P12 に点が無いのに他の出所には点がある ⇒ 被覆の穴の可能性
    - P12 の点が SMALL_N 未満 ⇒ 要約(中央値・割合)は数点で決まるので参考程度
    """
    ksj = points.get("ksj", 0)
    others = sum(v for k, v in points.items() if k != "ksj")
    if ksj == 0:
        return COVERAGE_NOTE if others > 0 else None
    if ksj < SMALL_N:
        return SMALL_N_NOTE
    return None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def region_stats(lon: float, lat: float, ctx: dict) -> dict:
    rmax = max(RADII_KM)
    near = {key: g.within(lon, lat, rmax) for key, g in ctx["grids"].items()}
    vol = [d for _, d in ctx["volcanoes"].within(lon, lat, rmax)]

    dlat, dlon = _box(lon, lat, rmax)
    lakes = []
    for rings, (x0, y0, x1, y1) in zip(ctx["lakes"], ctx["lake_boxes"]):
        if x1 < lon - dlon or x0 > lon + dlon or y1 < lat - dlat or y0 > lat + dlat:
            continue
        d = lake_distance_km(lon, lat, rings)
        if d <= rmax:
            lakes.append(d)

    veg = []
    for gun, d in ctx["mesh"].within(lon, lat, rmax):
        g = ctx["gunraku"].get(gun)
        if g is not None:
            veg.append((_sizendo_band(g["sizendo"]), d))

    by = {}
    for radius in RADII_KM:
        points = {key: sum(1 for _, d in near[key] if d <= radius) for key in LAYERS}

        props = [ctx["props"]["ksj"][k] for k, d in near["ksj"] if d <= radius]
        elev = [p["elevation_m"] for p in props if p.get("elevation_m") is not None]
        river = [p["distance_to_river_km"] for p in props if p.get("distance_to_river_km") is not None]
        geo = collections.Counter(p.get("geology_group") or "(不明)" for p in props)

        bands = collections.Counter(b for b, d in veg if d <= radius)
        total = sum(bands.values())
        by[str(radius)] = {
            "points": points,
            "coverage_note": coverage_note(points),
            "volcanoes": sum(1 for d in vol if d <= radius),
            "lakes": sum(1 for d in lakes if d <= radius),
            "vegetation_meshes": total,
            "vegetation_share": {b: bands.get(b, 0) / total for b in BANDS} if total else {},
            "onsen_summary": {
                "n": len(props),
                "elevation_median_m": _median(elev),
                "elevation_min_m": min(elev) if elev else None,
                "elevation_max_m": max(elev) if elev else None,
                "river_median_km": _median(river),
                "geology_share": {k: v / len(props) for k, v in geo.most_common()} if props else {},
            },
        }
    return by


def nearest_volcano(lon: float, lat: float, volcano_fc: dict) -> dict:
    best = min(
        ((haversine_km(lon, lat, *f["geometry"]["coordinates"]), f["properties"]["name"])
         for f in volcano_fc["features"]),
        key=lambda t: t[0],
    )
    return {"name": best[1], "distance_km": round(best[0], 3)}


def load_ctx() -> dict:
    grids, props = {}, {}
    for key, path in LAYERS.items():
        fc = json.loads((DATA / path).read_text(encoding="utf-8"))
        grids[key] = PointGrid([(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
                                 str(i)) for i, f in enumerate(fc["features"])])
        props[key] = [f["properties"] for f in fc["features"]]
    volcano_fc = json.loads((DATA / "volcanoes.geojson").read_text(encoding="utf-8"))
    lakes = load_lakes()
    gunraku, _, _ = load_tables()
    return {
        "grids": grids,
        "props": props,
        "volcano_fc": volcano_fc,
        "volcanoes": PointGrid([(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
                                 f["properties"]["name"]) for f in volcano_fc["features"]]),
        "lakes": lakes,
        "lake_boxes": [lake_bounds(r) for r in lakes],
        "mesh": MeshIndex(load_mesh()),
        "gunraku": gunraku,
    }


def main() -> None:
    ctx = load_ctx()
    regions = []
    for a in resolve_spec_anchors():
        regions.append({
            "id": f"spec-{a['label']}",
            "label": a["label"],
            "kind": "spec",
            "lon": a["lon"], "lat": a["lat"],
            "source": f"Wikidata {a['wikidata_id']}（{a['wikidata_label']}）",
            "wikidata_id": a["wikidata_id"],
            "classes": a["classes"],
            "nearest_volcano": nearest_volcano(a["lon"], a["lat"], ctx["volcano_fc"]),
            "by_radius": region_stats(a["lon"], a["lat"], ctx),
        })
        print(f"  {a['label']}: {a['wikidata_id']} 最寄り火山 {regions[-1]['nearest_volcano']}", flush=True)

    for f in ctx["volcano_fc"]["features"]:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        regions.append({
            "id": f"v-{p['volcano_id']}",
            "label": p["name"],
            "kind": "volcano",
            "lon": lon, "lat": lat,
            "source": f"気象庁 活火山（{p['volcano_id']}）",
            "volcano_id": str(p["volcano_id"]),
            "nearest_volcano": {"name": p["name"], "distance_km": 0.0},
            "by_radius": region_stats(lon, lat, ctx),
        })
    print(f"  火山を基準点にした地域 {sum(1 for r in regions if r['kind'] == 'volcano')}", flush=True)

    spec = [r for r in regions if r["kind"] == "spec"]
    overlaps = {}
    for radius in RADII_KM:
        pairs = []
        for i in range(len(spec)):
            for j in range(i + 1, len(spec)):
                d = haversine_km(spec[i]["lon"], spec[i]["lat"], spec[j]["lon"], spec[j]["lat"])
                if d < 2 * radius:
                    pairs.append({"pair": [spec[i]["label"], spec[j]["label"]], "distance_km": round(d, 3)})
        overlaps[str(radius)] = pairs

    write_json(OUT, {
        "radii_km": list(RADII_KM),
        "bands": BANDS,
        "method": (
            "地域は基準点から半径 10/25 km の円。点の数は出所ごとに数えて足さない。"
            "温泉の要約は国土数値情報 P12 の点だけで取る。湖沼は面の縁まで、植生はメッシュ中心が円に入るもの"
        ),
        "anchors_source": "Wikidata(CC0)・気象庁 活火山",
        "overlaps": overlaps,
        "regions": regions,
    })
    print(f"{OUT}: 地域 {len(regions)} / 重なり 25km {len(overlaps['25'])} 組", flush=True)


if __name__ == "__main__":
    main()
