"""植生(自然環境保全基礎調査 第5回 植生3次メッシュ)を扱う(設計書 §8/§18/§51)。

## データの性格

全国 **368,727 の 3 次メッシュ**(約 1 km 四方)に、代表する群落コードが 1 つずつ付く。
群落コード 579 種は群落表(898 行)で引け、そこから **植生自然度 1〜10** が定まる。
実測で欠測は 0。

自然度は「人の手が入っていない度合い」の段階で、1 = 市街地、10 = 自然草原。
設計書 §8 が求める「植生自然度」はこれである。

## 何を配るか

368,727 個の面をそのまま配ることはできない。**自然度でまとめた面**を作る ——
同じ自然度の隣り合うメッシュを 1 つの多角形に統合する…のではなく、
**メッシュを矩形のまま出し、自然度で色を塗る**。統合すると境界が実体より滑らかに見え、
「1 km の格子で測ったもの」という粒度が伝わらなくなるためである。

配る量を抑えるため、**表示用は自然度だけを持つ**(群落名は温泉点の属性として持たせる)。

## 出典

環境省生物多様性センター「第5回自然環境保全基礎調査 植生調査」
公共データ利用規約(第1.0版) PDL1.0 — 出典表示のみ
https://www.biodic.go.jp/kiso/vg/vg_kiso.html
"""
from __future__ import annotations

import collections
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, RAW, write_json
from etl.mesh import mesh3_center, point_to_mesh3

VEG_DIR = RAW / "biodic"
MESH_CSV = VEG_DIR / "veg05m01" / "veg05mesh.csv"
GUNRAKU_CSV = VEG_DIR / "veg_c02" / "veg_gunraku.csv"
SIZENDO_CSV = VEG_DIR / "veg_c02" / "veg_sizendo.csv"
KUBUN_CSV = VEG_DIR / "veg_c02" / "veg_kubun.csv"

OUT_LEGEND = DATA / "vegetation_legend.json"
OUT_STATS = DATA / "vegetation_stats.json"

LICENSE = {
    "source": "環境省生物多様性センター",
    "dataset": "第5回自然環境保全基礎調査 植生調査 3次メッシュデータ(1992-1996)",
    "source_url": "https://www.biodic.go.jp/kiso/vg/vg_kiso.html",
    "license": "公共データ利用規約(第1.0版) PDL1.0",
    "license_url": "https://www.biodic.go.jp/copyright/terms_of_service.html",
    "download_date": "2026-09-09",
}


def _read(path: Path) -> list[list[str]]:
    if not path.exists():
        raise SystemExit(
            f"{path} が無い。README の手順で取得し、7-Zip で展開すること"
        )
    with io.open(path, encoding="cp932", newline="") as f:
        return list(csv.reader(f))


def load_tables() -> tuple[dict, dict, dict]:
    """群落コード → {名前, 自然度, 区分} と、自然度・区分の凡例を返す。"""
    gun_rows = _read(GUNRAKU_CSV)[1:]
    gunraku = {r[1]: {"name": r[2], "sizendo": r[4], "kubun": r[0]} for r in gun_rows}
    sizendo = {r[0]: {"label": r[1], "content": r[2], "criterion": r[3] if len(r) > 3 else ""}
               for r in _read(SIZENDO_CSV)[1:]}
    kubun = {r[0]: {"symbol": r[1], "name": r[2]} for r in _read(KUBUN_CSV)[1:]}
    return gunraku, sizendo, kubun


def load_mesh() -> dict[str, str]:
    """メッシュコード → 群落コード。"""
    rows = _read(MESH_CSV)[1:]
    return {r[0]: r[1] for r in rows}


def build() -> dict:
    gunraku, sizendo, kubun = load_tables()
    mesh = load_mesh()

    # 群落コードが群落表で引けることを、使う前に全域で確かめる(HC-069)
    unknown = sorted({c for c in mesh.values() if c not in gunraku})
    if unknown:
        raise SystemExit(f"群落表で引けないコードが {len(unknown)} 種ある: {unknown[:5]}")
    bad_sizendo = sorted({gunraku[c]["sizendo"] for c in mesh.values()} - set(sizendo))
    if bad_sizendo:
        raise SystemExit(f"自然度の凡例に無いコード: {bad_sizendo}")

    by_sizendo = collections.Counter(gunraku[c]["sizendo"] for c in mesh.values())
    by_kubun = collections.Counter(gunraku[c]["kubun"] for c in mesh.values())

    return {
        **LICENSE,
        "processing_method": (
            "3 次メッシュ(約 1 km)ごとの群落コードを群落表で引き、植生自然度に直した。"
            "群落コードは 579 種すべてが群落表にあり、自然度の欠測は 0"
        ),
        "counts": {
            "meshes": len(mesh),
            "community_codes_used": len({*mesh.values()}),
            "community_codes_in_table": len(gunraku),
        },
        "sizendo_legend": [
            {"code": k, **v, "meshes": by_sizendo.get(k, 0)}
            for k, v in sorted(sizendo.items())
        ],
        "kubun_legend": [
            {"code": k, **v, "meshes": by_kubun.get(k, 0)}
            for k, v in sorted(kubun.items())
        ],
    }


def attach(path: str, gunraku: dict, sizendo: dict, kubun: dict, mesh: dict[str, str]) -> tuple[int, int]:
    """点に、その点が入る 3 次メッシュの植生を付ける。"""
    p = DATA / path
    fc = json.loads(p.read_text(encoding="utf-8"))
    got = 0
    for f in fc["features"]:
        lon, lat = f["geometry"]["coordinates"]
        code = point_to_mesh3(lon, lat)
        g = gunraku.get(mesh.get(code, ""))
        pr = f["properties"]
        pr["vegetation_mesh"] = code
        if g is None:
            # 海上や調査範囲外。埋めない
            pr["vegetation_community"] = None
            pr["vegetation_naturalness"] = None
            pr["vegetation_naturalness_label"] = None
            pr["vegetation_zone"] = None
            continue
        got += 1
        pr["vegetation_community"] = g["name"]
        pr["vegetation_naturalness"] = g["sizendo"]
        pr["vegetation_naturalness_label"] = sizendo[g["sizendo"]]["content"]
        pr["vegetation_zone"] = kubun.get(g["kubun"], {}).get("name")
    fc["metadata"].setdefault("enrichment", {})
    fc["metadata"]["enrichment"]["vegetation"] = {
        **LICENSE,
        "method": "点が入る 3 次メッシュ(約 1 km)の代表群落を引いた。メッシュが無い点は欠測",
        "coverage": f"{got}/{len(fc['features'])}",
    }
    write_json(p, fc)
    return got, len(fc["features"])


if __name__ == "__main__":
    doc = build()
    write_json(OUT_STATS, doc, indent=1)
    c = doc["counts"]
    print(f"{OUT_STATS}: メッシュ {c['meshes']:,} / 群落コード {c['community_codes_used']} 種")
    for row in doc["sizendo_legend"]:
        if row["meshes"]:
            print(f"  自然度 {row['code']} {row['label']:>3} {row['content'][:20]:<22} "
                  f"{row['meshes']:>7,} ({100*row['meshes']/c['meshes']:.1f}%)")

    gunraku, sizendo, kubun = load_tables()
    mesh = load_mesh()
    for path in ("onsen.geojson", "control.geojson", "onsen_wikidata.geojson", "onsen_facility.geojson", "onsen_wikipedia.geojson"):
        got, total = attach(path, gunraku, sizendo, kubun, mesh)
        print(f"{path}: 植生 {got}/{total}")
