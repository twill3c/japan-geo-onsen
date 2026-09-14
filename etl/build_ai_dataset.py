"""AI 用のデータセットを作る(設計書 Phase 4 §52 / docs/ai_preregistration.md)。

地点ごとに地形・地質・火山・水・植生を結合した表を 1 枚作る。
正例は P12 の温泉 1,320 点、負例は P12 の温泉以外の観光資源から都道府県ごとに同数を選んだ
1,320 点(対照群・統計ページと同じもの)。

**負例は「温泉が無い場所」ではない**(設計書 §33)。当てる問いは
「P12 に登録された地点が温泉の分類かどうか」である。

## 漏れを入れない

ラベルの作り方を映す列(名前に温泉を含むか・出所・分類コード・ID・住所・都道府県)は
特徴量に入れない。都道府県は**検証の分割に使う群**としてだけ持つ。
周辺の温泉の数は正例にしか計算していないので、これも入れない。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, write_json

OUT_DIR = DATA / "ai"
OUT_CSV = OUT_DIR / "dataset.csv"
OUT_DICT = OUT_DIR / "dataset_dictionary.json"

NUMERIC = [
    "elevation_m",
    "slope_deg",
    "local_relief_m",
    "distance_to_volcano_km",
    "distance_to_river_km",
    "distance_to_lake_km",
    "vegetation_naturalness",
]
CATEGORICAL = ["geology_group"]
FEATURES = NUMERIC + CATEGORICAL
GROUP = "prefecture"
LABEL = "label"
ID = "point_id"

# 特徴量に入れてはならない列(ラベルそのもの、またはラベルの作り方を映す)
LEAKY = {
    "name", "name_has_onsen", "provenance", "kind_name", "category_code", "matched_by",
    "onsen_id", "source_id", "address", "prefecture", "prefecture_code", "city_code",
    "surroundings",
}

DESCRIPTIONS = {
    "elevation_m": "標高 m(国土地理院 標高タイル z14)",
    "slope_deg": "傾斜 度(Horn 法)",
    "local_relief_m": "局所起伏 m(±16 画素の最大−最小)",
    "distance_to_volcano_km": "最寄りの活火山までの距離 km(気象庁 111)",
    "distance_to_river_km": "最寄りの河川までの距離 km(国土数値情報 W05 全区間)",
    "distance_to_lake_km": "最寄りの湖沼までの距離 km(国土数値情報 W09)",
    "vegetation_naturalness": "植生自然度 1〜10(環境省 第5回基礎調査。98/99/00 は欠測)",
    "geology_group": "地質の大区分(産総研 シームレス地質図V2)",
    "prefecture": "都道府県(特徴量ではなく検証の分割に使う群)",
    "label": "1 = P12 の温泉 / 0 = P12 の温泉以外の観光資源(温泉が無い場所ではない)",
}


def _naturalness(v) -> float | None:
    """植生自然度を数にする。1〜10 以外(98 自然裸地・99 開放水域・00 不明)は欠測。"""
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return float(n) if 1 <= n <= 10 else None


def load_rows() -> list[dict]:
    rows = []
    for path, label in (("onsen.geojson", 1), ("control.geojson", 0)):
        fc = json.loads((DATA / path).read_text(encoding="utf-8"))
        for i, f in enumerate(fc["features"]):
            p = f["properties"]
            row = {
                ID: p.get("onsen_id") or f"{path}#{i}",
                LABEL: label,
                GROUP: p["prefecture"],
            }
            for k in NUMERIC:
                v = _naturalness(p.get(k)) if k == "vegetation_naturalness" else p.get(k)
                row[k] = None if v is None else float(v)
            row["geology_group"] = p.get("geology_group")
            rows.append(row)
    return rows


def main() -> None:
    rows = load_rows()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cols = [ID, LABEL, GROUP, *FEATURES]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in cols})
    write_json(OUT_DICT, {
        "note": ("P12 に登録された地点が温泉の分類かどうかを当てるための表。"
                 "負例は『温泉が無い場所』ではない(設計書 §33)"),
        "rows": len(rows),
        "positives": sum(r[LABEL] for r in rows),
        "negatives": sum(1 - r[LABEL] for r in rows),
        "columns": [{"name": c, "description": DESCRIPTIONS.get(c, "")} for c in cols],
        "missing": {k: sum(1 for r in rows if r[k] is None) for k in FEATURES},
        "excluded_as_leaky": sorted(LEAKY),
        "not_available": ["断層(未取り込み)", "泉温・湧出量・泉質(地点別の公開データが無い)"],
    }, indent=1)
    print(f"{OUT_CSV}: {len(rows)} 行(正 {sum(r[LABEL] for r in rows)} / 負 {sum(1 - r[LABEL] for r in rows)})")


if __name__ == "__main__":
    main()
