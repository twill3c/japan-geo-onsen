"""対照群を作る。

設計書 §33 が言うとおり、温泉の点は「人が見つけて登録した場所」である。
だから「温泉は標高 800 m 付近に多い」と言っても、それが温泉の性質なのか
「人が観光地を登録する場所の性質」なのかは、温泉だけを見ても分からない。

そこで、**同じ P12 観光資源データの温泉以外の点**を対照に取る。
同じ調査・同じ提出経路・同じ都道府県構成なので、「人が登録した場所」という偏りは揃う。
都道府県ごとに温泉と同数を抽出する(足りなければあるだけ)。

抽出は seed 固定の擬似乱数で行い、seed を成果物に残す(再現できるように)。
"""
from __future__ import annotations

import glob
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shapefile  # pyshp

from etl.build_onsen_base import CATEGORY_ONSEN_HEALTH, KIND_ONSEN, PREF_NAMES, clean
from etl.common import DATA, RAW, ensure_p12, write_json

SEED = 20260907
OUT = DATA / "control.geojson"


def build() -> dict:
    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    want: dict[str, int] = {}
    for f in onsen["features"]:
        p = f["properties"]["prefecture_code"]
        want[p] = want.get(p, 0) + 1

    ensure_p12()
    pool: dict[str, list[dict]] = {}
    scanned = 0
    for path in sorted(glob.glob(str(RAW / "ksj" / "P12" / "P12a-14_*.shp"))):
        reader = shapefile.Reader(path, encoding="cp932")
        names = [f[0] for f in reader.fields[1:]]
        for sr in reader.iterShapeRecords():
            scanned += 1
            rec = dict(zip(names, sr.record))
            kind, code = clean(rec["P12_005"]), clean(rec["P12_007"])
            if kind == KIND_ONSEN or code == CATEGORY_ONSEN_HEALTH:
                continue  # 温泉側は対照に入れない
            if not sr.shape.points:
                continue
            pref = clean(rec["P12_003"])
            if want.get(pref, 0) == 0:
                continue  # 温泉が 1 点も無い県は比較の土俵に乗らない
            lon, lat = sr.shape.points[0]
            pool.setdefault(pref, []).append({
                "id": f"ctl-{pref}-{clean(rec['P12_001'])}",
                "name": clean(rec["P12_002"]),
                "pref": pref,
                "code": code,
                "kind": kind if kind and kind != "‐" else None,
                "lonlat": [round(lon, 6), round(lat, 6)],
            })

    rng = random.Random(SEED)
    features = []
    short: dict[str, list[int]] = {}
    for pref, n in sorted(want.items()):
        cand = pool.get(pref, [])
        take = min(n, len(cand))
        if take < n:
            short[pref] = [n, take]
        for c in rng.sample(cand, take):
            features.append({
                "type": "Feature",
                "id": c["id"],
                "geometry": {"type": "Point", "coordinates": c["lonlat"]},
                "properties": {
                    "control_id": c["id"], "name": c["name"],
                    "prefecture_code": pref,
                    "prefecture": PREF_NAMES[int(pref)] if pref.isdigit() else None,
                    "category_code": c["code"], "kind_name": c["kind"],
                },
            })

    # 一意性は作った側の責任。衝突したら黙って畳まず止める(HC-200/HC-201)
    ids = [f["id"] for f in features]
    if len(ids) != len(set(ids)):
        raise SystemExit("control_id が一意でない")

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "purpose": "温泉点の対照群(同じ P12 観光資源データの温泉以外の点)",
            "source": "国土交通省 国土数値情報 観光資源データ(P12) 2014年版",
            "sampling": f"都道府県ごとに温泉と同数を無作為抽出(seed={SEED})",
            "seed": SEED,
            "counts": {
                "scanned_points": scanned,
                "onsen_total": len(onsen["features"]),
                "control_total": len(features),
                "prefectures": len(want),
                "short_of_target": short,
            },
        },
    }


if __name__ == "__main__":
    fc = build()
    write_json(OUT, fc)
    c = fc["metadata"]["counts"]
    print(f"{OUT}: 対照 {c['control_total']} 点(温泉 {c['onsen_total']} 点に対して)")
    if c["short_of_target"]:
        print(f"  候補が足りなかった県 {len(c['short_of_target'])}: {c['short_of_target']}")
