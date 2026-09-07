"""気象庁の火山一覧 JSON から火山点 GeoJSON を作る。

件数オラクル(SPEC G-04):
    気象庁は「我が国には 111 の活火山があります」と公表している
    (https://www.data.jma.go.jp/svd/vois/data/tokyo/STOCK/kaisetsu/katsukazan_toha/katsukazan_toha.html
     2026-09-07 取得)。
    一方 volcano_list.json は 120 件ある。内訳を実測すると

        120 = 111(活火山) + 3(座標を持たない UI 用の疑似項目) + 6(親火山の火口細分)

    となり、公表値と一致する。この分解が崩れたら ETL を止める。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, RAW, write_json

SRC = RAW / "jma" / "volcano_list.json"
OUT = DATA / "volcanoes.geojson"

# 気象庁の公表値(外部権威)。取得日 2026-09-07。
JMA_PUBLISHED_ACTIVE_VOLCANOES = 111


def classify(entries: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(活火山, 火口細分, 疑似項目) に分ける。

    細分の判定は名簿自身から導く: 名称が「<親の名称>（…」の形で、
    その親の名称が名簿に実在するものを細分とみなす。番号の決め打ちはしない。
    """
    names = {e.get("name_jp", "") for e in entries}
    volcanoes: list[dict] = []
    subdivisions: list[dict] = []
    pseudo: list[dict] = []
    for e in entries:
        if "latlon" not in e:
            pseudo.append(e)
            continue
        name = e.get("name_jp", "")
        head = name.split("（", 1)[0]
        if "（" in name and head in names and head != name:
            subdivisions.append(e)
        else:
            volcanoes.append(e)
    return volcanoes, subdivisions, pseudo


def build() -> dict:
    import json

    entries = json.loads(SRC.read_text(encoding="utf-8"))
    volcanoes, subdivisions, pseudo = classify(entries)

    if len(volcanoes) != JMA_PUBLISHED_ACTIVE_VOLCANOES:
        raise SystemExit(
            f"件数オラクル不一致: 活火山として {len(volcanoes)} 件を得たが、"
            f"気象庁公表値は {JMA_PUBLISHED_ACTIVE_VOLCANOES} 件。"
            f"(名簿 {len(entries)} 件 / 細分 {len(subdivisions)} 件 / 疑似 {len(pseudo)} 件)"
        )

    features = []
    for e in sorted(volcanoes, key=lambda x: x["code"]):
        lat, lon = float(e["latlon"][0]), float(e["latlon"][1])
        subs = [s["name_jp"] for s in subdivisions if s["name_jp"].startswith(e["name_jp"] + "（")]
        features.append({
            "type": "Feature",
            "id": f"volcano-{e['code']}",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "volcano_id": e["code"],
                "name": e["name_jp"],
                "name_en": e.get("name_en"),
                # 噴火警戒レベルが運用されている火山かどうか(名簿の levelOperation)
                "warning_level_operated": bool(e.get("levelOperation")),
                "craters": subs,
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "気象庁",
            "dataset": "火山一覧(bosai/volcano/const/volcano_list.json)",
            "source_url": "https://www.jma.go.jp/bosai/volcano/const/volcano_list.json",
            "license": "気象庁ホームページの利用について(出典明示)",
            "license_url": "https://www.jma.go.jp/jma/kishou/info/coment.html",
            "download_date": "2026-09-07",
            "processing_method": "名簿 120 件から、座標を持たない疑似項目 3 件と親火山の火口細分 6 件を除いて 111 件",
            "counts": {
                "entries": len(entries),
                "volcanoes": len(volcanoes),
                "subdivisions": len(subdivisions),
                "pseudo": len(pseudo),
                "jma_published": JMA_PUBLISHED_ACTIVE_VOLCANOES,
            },
        },
    }


if __name__ == "__main__":
    fc = build()
    write_json(OUT, fc)
    m = fc["metadata"]["counts"]
    lv = sum(1 for f in fc["features"] if f["properties"]["warning_level_operated"])
    print(f"{OUT}: {len(fc['features'])} 火山 "
          f"(名簿 {m['entries']} / 細分 {m['subdivisions']} / 疑似 {m['pseudo']}) "
          f"噴火警戒レベル運用 {lv} 火山")
