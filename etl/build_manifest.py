"""出荷データの台帳を作る(SPEC F-11 / N-04 / 設計書 §45・§47)。

各成果物の「出典・利用条件・取得日・加工方法・件数・バイト数」を 1 か所に集める。
件数は成果物を読み直して数える —— 生成器が申告した数をそのまま写さない。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, write_json

OUT = DATA / "manifest.json"

PRODUCTS = ["volcanoes.geojson", "onsen.geojson", "control.geojson",
            "rivers.geojson", "lakes.geojson", "stats.json"]


def main() -> None:
    entries = []
    for name in PRODUCTS:
        path = DATA / name
        if not path.exists():
            raise SystemExit(f"{name} が無い。ETL を先に走らせること")
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
        entry = {
            "file": name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if doc.get("type") == "FeatureCollection":
            # 申告ではなく実物を数える
            entry["features"] = len(doc["features"])
            meta = doc.get("metadata", {})
            for k in ("source", "dataset", "source_url", "license", "license_url",
                      "download_date", "processing_method", "purpose", "sampling"):
                if k in meta:
                    entry[k] = meta[k]
            if "enrichment" in meta:
                entry["enrichment"] = meta["enrichment"]
        else:
            entry["axes"] = len(doc.get("axes", []))
            entry["method"] = doc.get("method")
        entries.append(entry)

    total = sum(e["bytes"] for e in entries)
    write_json(OUT, {
        "generated": "2026-09-08",
        "note": "件数は成果物を読み直して数えたもの。生成器の申告は写していない。",
        "total_bytes": total,
        "products": entries,
    }, indent=1)
    print(f"{OUT}: {len(entries)} 件 / 合計 {total/1024/1024:.2f} MB")
    for e in entries:
        n = e.get("features", e.get("axes"))
        print(f"  {e['file']:<22} {e['bytes']/1024:8.1f} KB  {n}")


if __name__ == "__main__":
    main()
