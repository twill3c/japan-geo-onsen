"""河川(W05)と湖沼(W09)の全国被覆を、実装を書く前に測る(HC-069)。

「どれを配るか」は、件数と頂点数を実測してから決める。
zip は展開しない —— 297 MB を 1 GB に増やさずに済むし、配布形のまま読む方が
「展開物とどちらが正か」で迷わない(HC-139)。
"""
from __future__ import annotations

import collections
import glob
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shapefile

from etl.common import RAW

UNNAMED = "名称不明"


def open_shp_in_zip(zip_path: str, suffix: str):
    """zip の中のシェープファイルを展開せずに開く。"""
    z = zipfile.ZipFile(zip_path)
    base = None
    for n in z.namelist():
        if n.endswith(suffix + ".shp"):
            base = n[: -len(".shp")]
            break
    if base is None:
        return None
    return shapefile.Reader(
        shp=io.BytesIO(z.read(base + ".shp")),
        dbf=io.BytesIO(z.read(base + ".dbf")),
        shx=io.BytesIO(z.read(base + ".shx")),
        encoding="cp932",
    )


def survey_rivers() -> None:
    zips = sorted(glob.glob(str(RAW / "ksj" / "W05" / "*.zip")))
    print(f"河川 W05: {len(zips)} 県")
    sec = collections.Counter()
    vtx_by_sec = collections.Counter()
    main_stem = collections.Counter()
    unnamed = 0
    total_seg = 0
    total_vtx = 0
    for zp in zips:
        r = open_shp_in_zip(zp, "Stream")
        if r is None:
            print(f"  Stream が無い: {zp}")
            continue
        names = [f[0] for f in r.fields[1:]]
        for sr in r.iterShapeRecords():
            d = dict(zip(names, sr.record))
            s = str(d["W05_003"]).replace("\x00", "").strip()
            code = str(d["W05_002"]).replace("\x00", "").strip()
            nm = str(d["W05_004"]).replace("\x00", "").strip()
            n = len(sr.shape.points)
            sec[s] += 1
            vtx_by_sec[s] += n
            if code.endswith("0000"):
                main_stem[s] += 1
            if nm == UNNAMED or not nm:
                unnamed += 1
            total_seg += 1
            total_vtx += n
    print(f"  区間 {total_seg:,} / 頂点 {total_vtx:,}")
    print(f"  河川名が「{UNNAMED}」または空: {unnamed:,} ({100*unnamed/total_seg:.1f}%)")
    print("  区間種別   区間数      頂点数      うち本川(コード末尾0000)")
    for s, c in sorted(sec.items()):
        print(f"   {s:>3}  {c:>10,}  {vtx_by_sec[s]:>12,}  {main_stem[s]:>10,}")


def survey_lakes() -> None:
    zp = str(RAW / "ksj" / "W09" / "W09-05_GML.zip")
    r = open_shp_in_zip(zp, "Lake")
    if r is None:
        print("湖沼: Lake が無い")
        return
    names = [f[0] for f in r.fields[1:]]
    print(f"\n湖沼 W09: 属性 {names}  形状タイプ {r.shapeType}")
    n_poly = 0
    n_vtx = 0
    named = 0
    areas = []
    sample = []
    for sr in r.iterShapeRecords():
        d = dict(zip(names, sr.record))
        n_poly += 1
        n_vtx += len(sr.shape.points)
        nm = str(d.get(names[1], "")).replace("\x00", "").strip()
        if nm:
            named += 1
        if len(sample) < 3:
            sample.append({k: str(v).replace("\x00", "").strip() for k, v in d.items()})
    print(f"  面 {n_poly:,} / 頂点 {n_vtx:,}  名称あり {named:,}")
    for s in sample:
        print("   ", s)


if __name__ == "__main__":
    survey_rivers()
    survey_lakes()
