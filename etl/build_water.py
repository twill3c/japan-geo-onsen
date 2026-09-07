"""河川(W05)と湖沼(W09)を扱う。

## 実測(2026-09-08)してから決めたこと

全国の河川は **286,437 区間・15,459,553 頂点**ある。これを一度に索引へ載せると
メモリが持たないので、**県ごとに読み、その県の索引に対して近くの点だけを問い合わせ、
走査中の最小値を更新する**。索引はその県の分だけ生きていればよい。

表示に載せるのは **区間種別 1 と 5(1 級河川の直轄区間)= 11,507 区間**だけ。
1/2/5/6(1 級河川すべて)は 72,141 区間・332 万頂点あり、間引いても配れる大きさに
ならない。**距離の計算には全 286,437 区間を使う**ので、表示の絞り込みは
「地図に描く線」だけの話である。

湖沼は 556 面・474,921 頂点。こちらは全部載る。

## 利用条件

W05 河川は **非商用限定**。W09 湖沼は商用可。標準の約款と違うので別に持つ。
"""
from __future__ import annotations

import collections
import glob
import io
import json
import math
import sys
import zipfile
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shapefile

from etl.common import DATA, RAW, point_segment_distance_km, write_json

CELL = 0.05            # 格子の一辺(度)
MARGIN_DEG = 0.6       # 県の外接矩形をこれだけ広げた範囲の点だけを問い合わせる
MAX_RINGS = 12         # 0.6 度ぶん。これを超えて探さない(見つからなければ欠測)
KEEP = 8               # 篩で残す候補数。この分だけ厳密な距離を計算する
UNNAMED = "名称不明"

DISPLAY_SECTIONS = {"1", "5"}   # 1 級河川の直轄区間
SIMPLIFY_TOL = 0.0005           # 度。およそ 45 m

RIVER_LICENSE = {
    "source": "国土交通省 国土数値情報",
    "dataset": "河川データ(W05)",
    "source_url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html",
    "license": "国土数値情報 利用約款(**非商用限定**)",
    "license_url": "https://nlftp.mlit.go.jp/ksj/other/agreement.html",
    "download_date": "2026-09-08",
}
LAKE_LICENSE = {
    "source": "国土交通省 国土数値情報",
    "dataset": "湖沼データ(W09) 2005年版",
    "source_url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W09-v2_2.html",
    "license": "国土数値情報 利用約款(商用可)",
    "license_url": "https://nlftp.mlit.go.jp/ksj/other/agreement.html",
    "download_date": "2026-09-08",
}


def open_shp_in_zip(zip_path: str, suffix: str):
    """zip の中のシェープファイルを展開せずに開く(HC-139: 配布形のまま読む)。"""
    z = zipfile.ZipFile(zip_path)
    base = next((n[: -len(".shp")] for n in z.namelist() if n.endswith(suffix + ".shp")), None)
    if base is None:
        return None
    return shapefile.Reader(
        shp=io.BytesIO(z.read(base + ".shp")),
        dbf=io.BytesIO(z.read(base + ".dbf")),
        shx=io.BytesIO(z.read(base + ".shx")),
        encoding="cp932",
    )


def clean(v) -> str:
    return str(v).replace("\x00", "").strip()


class SegmentIndex:
    """線分を 0.05 度の格子に入れて、点の近傍だけを見られるようにする。

    名前は文字列で持たず整数の id にする(線分が数百万本になるため)。
    """

    def __init__(self) -> None:
        self.x1 = array("d"); self.y1 = array("d")
        self.x2 = array("d"); self.y2 = array("d")
        self.name_id = array("i")
        self.names: list[str] = []
        self._name_index: dict[str, int] = {}
        self.cells: dict[tuple[int, int], array] = collections.defaultdict(lambda: array("i"))

    def __len__(self) -> int:
        return len(self.x1)

    def _nid(self, name: str) -> int:
        i = self._name_index.get(name)
        if i is None:
            i = len(self.names)
            self.names.append(name)
            self._name_index[name] = i
        return i

    def add_line(self, pts, name: str) -> None:
        nid = self._nid(name)
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            if ax == bx and ay == by:
                continue
            k = len(self.x1)
            self.x1.append(ax); self.y1.append(ay)
            self.x2.append(bx); self.y2.append(by)
            self.name_id.append(nid)
            i0, i1 = sorted((int(math.floor(ax / CELL)), int(math.floor(bx / CELL))))
            j0, j1 = sorted((int(math.floor(ay / CELL)), int(math.floor(by / CELL))))
            for ci in range(i0, i1 + 1):
                for cj in range(j0, j1 + 1):
                    self.cells[(ci, cj)].append(k)

    def nearest(self, lon: float, lat: float):
        """(距離km, 名前) を返す。MAX_RINGS 内に無ければ (None, None)。

        **二段構え**にしてある。内側の篩は局所平面の距離だけで回し(三角関数を呼ばない)、
        最後に上位 KEEP 件へ厳密な point_segment_distance_km を当てて最小を取る。

        一段で厳密な関数を全候補に当てると、垂線の足が線分の外に落ちる場合に
        haversine(三角関数 5 回)が走る。河川の短い区間ではその分岐が大半なので、
        全国走査では約 12 億回になり CPU 51 分でも終わらなかった(実測 2026-09-08)。
        """
        km_per_deg = 111.19493
        kx = km_per_deg * math.cos(math.radians(lat))
        ky = km_per_deg
        ci = int(math.floor(lon / CELL))
        cj = int(math.floor(lat / CELL))
        # 上位候補を (篩の距離, 線分 id) で保持する
        cand: list[tuple[float, int]] = []
        worst_kept = float("inf")
        seen: set[int] = set()
        x1, y1, x2, y2 = self.x1, self.y1, self.x2, self.y2
        for ring in range(MAX_RINGS + 1):
            for di in range(-ring, ring + 1):
                for dj in range(-ring, ring + 1):
                    if ring > 0 and max(abs(di), abs(dj)) != ring:
                        continue
                    for k in self.cells.get((ci + di, cj + dj), ()):
                        if k in seen:
                            continue
                        seen.add(k)
                        ax = (x1[k] - lon) * kx
                        ay = (y1[k] - lat) * ky
                        bx = (x2[k] - lon) * kx
                        by = (y2[k] - lat) * ky
                        ex, ey = bx - ax, by - ay
                        den = ex * ex + ey * ey
                        if den == 0.0:
                            qx, qy = ax, ay
                        else:
                            t = -(ax * ex + ay * ey) / den
                            if t < 0.0:
                                t = 0.0
                            elif t > 1.0:
                                t = 1.0
                            qx, qy = ax + ex * t, ay + ey * t
                        d2 = qx * qx + qy * qy
                        if len(cand) < KEEP or d2 < worst_kept:
                            cand.append((d2, k))
                            if len(cand) > KEEP * 4:
                                cand.sort()
                                del cand[KEEP:]
                                worst_kept = cand[-1][0]
            if cand:
                cand.sort()
                if len(cand) > KEEP:
                    del cand[KEEP:]
                worst_kept = cand[-1][0]
                safe = ring * CELL * kx
                if math.sqrt(cand[0][0]) <= safe:
                    break
        if not cand:
            return (None, None)
        best = float("inf")
        best_nid = -1
        for _, k in cand[:KEEP]:
            d = point_segment_distance_km(lon, lat, x1[k], y1[k], x2[k], y2[k])
            if d < best:
                best, best_nid = d, self.name_id[k]
        return (best, self.names[best_nid])


def simplify(pts, tol: float):
    """Douglas-Peucker。表示用に頂点を落とす(距離の計算には使わない)。"""
    if len(pts) < 3:
        return list(pts)
    stack = [(0, len(pts) - 1)]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    while stack:
        s, e = stack.pop()
        ax, ay = pts[s]
        bx, by = pts[e]
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        worst, idx = -1.0, -1
        for i in range(s + 1, e):
            px, py = pts[i]
            if denom == 0.0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / denom
                t = 0.0 if t < 0 else (1.0 if t > 1 else t)
                d = math.hypot(px - (ax + dx * t), py - (ay + dy * t))
            if d > worst:
                worst, idx = d, i
        if worst > tol and idx > 0:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [pts[i] for i in range(len(pts)) if keep[i]]


def load_points() -> list[dict]:
    """温泉と対照の全点を、走査中の最小値を持つ器として並べる。"""
    out = []
    for path in ("onsen.geojson", "control.geojson"):
        fc = json.loads((DATA / path).read_text(encoding="utf-8"))
        for f in fc["features"]:
            lon, lat = f["geometry"]["coordinates"]
            out.append({"file": path, "lon": lon, "lat": lat,
                        "river_km": None, "river_name": None,
                        "lake_km": None, "lake_name": None})
    return out


def scan_rivers(points: list[dict]) -> dict:
    zips = sorted(glob.glob(str(RAW / "ksj" / "W05" / "*.zip")))
    if not zips:
        raise SystemExit("raw/ksj/W05 に zip が無い。README の手順で取得すること")
    display: list[dict] = []
    n_seg = n_vtx = 0
    vtx_before = vtx_after = 0
    for zi, zp in enumerate(zips, 1):
        r = open_shp_in_zip(zp, "Stream")
        if r is None:
            raise SystemExit(f"Stream が無い: {zp}")
        names = [f[0] for f in r.fields[1:]]
        index = SegmentIndex()
        for sr in r.iterShapeRecords():
            d = dict(zip(names, sr.record))
            pts = sr.shape.points
            if len(pts) < 2:
                continue
            n_seg += 1
            n_vtx += len(pts)
            nm = clean(d["W05_004"])
            index.add_line(pts, nm)
            if clean(d["W05_003"]) in DISPLAY_SECTIONS:
                vtx_before += len(pts)
                s = simplify(pts, SIMPLIFY_TOL)
                vtx_after += len(s)
                display.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [[round(x, 5), round(y, 5)] for x, y in s]},
                    "properties": {"name": None if nm == UNNAMED else nm},
                })
        # この県の外接矩形に近い点だけを問い合わせる
        bb = r.bbox
        lo_x, lo_y, hi_x, hi_y = bb[0] - MARGIN_DEG, bb[1] - MARGIN_DEG, bb[2] + MARGIN_DEG, bb[3] + MARGIN_DEG
        asked = 0
        for p in points:
            if not (lo_x <= p["lon"] <= hi_x and lo_y <= p["lat"] <= hi_y):
                continue
            asked += 1
            d, nm = index.nearest(p["lon"], p["lat"])
            if d is not None and (p["river_km"] is None or d < p["river_km"]):
                p["river_km"] = d
                p["river_name"] = nm
        print(f"  [{zi}/{len(zips)}] {Path(zp).name} 線分 {len(index):,} 問合せ {asked}", flush=True)
        del index
    return {"features": display, "segments": n_seg, "vertices": n_vtx,
            "vtx_before": vtx_before, "vtx_after": vtx_after}


def scan_lakes(points: list[dict]) -> dict:
    zp = str(RAW / "ksj" / "W09" / "W09-05_GML.zip")
    r = open_shp_in_zip(zp, "Lake")
    if r is None:
        raise SystemExit("W09 の Lake が無い")
    names = [f[0] for f in r.fields[1:]]
    index = SegmentIndex()
    feats = []
    vtx_before = vtx_after = 0
    for sr in r.iterShapeRecords():
        d = dict(zip(names, sr.record))
        nm = clean(d["W09_001"])
        pts = sr.shape.points
        if len(pts) < 3:
            continue
        index.add_line(list(pts) + [pts[0]], nm or "(名称なし)")
        vtx_before += len(pts)
        parts = list(sr.shape.parts) + [len(pts)]
        rings = []
        for i in range(len(parts) - 1):
            ring = simplify(pts[parts[i]:parts[i + 1]], SIMPLIFY_TOL)
            if len(ring) >= 4:
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                rings.append([[round(x, 5), round(y, 5)] for x, y in ring])
                vtx_after += len(ring)
        if rings:
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings},
                          "properties": {"name": nm or None}})
    for p in points:
        d, nm = index.nearest(p["lon"], p["lat"])
        p["lake_km"], p["lake_name"] = d, nm
    return {"features": feats, "polygons": len(feats), "index": len(index),
            "vtx_before": vtx_before, "vtx_after": vtx_after}


def main() -> None:
    points = load_points()
    print(f"対象の点 {len(points)}")

    print("河川を走査…", flush=True)
    riv = scan_rivers(points)
    write_json(DATA / "rivers.geojson", {
        "type": "FeatureCollection",
        "features": riv["features"],
        "metadata": {
            **RIVER_LICENSE,
            "processing_method": (
                f"全 {riv['segments']:,} 区間・{riv['vertices']:,} 頂点のうち、"
                f"区間種別 {'/'.join(sorted(DISPLAY_SECTIONS))}(1 級河川の直轄区間)だけを表示用に抽出し、"
                f"Douglas-Peucker(許容 {SIMPLIFY_TOL} 度 ≒ 45 m)で頂点を "
                f"{riv['vtx_before']:,} → {riv['vtx_after']:,} に間引いた。"
                "**距離の計算には間引く前の全区間を使っている**"
            ),
            "counts": {"segments_all": riv["segments"], "vertices_all": riv["vertices"],
                       "features_displayed": len(riv["features"]),
                       "vertices_before_simplify": riv["vtx_before"],
                       "vertices_after_simplify": riv["vtx_after"]},
        },
    })
    print(f"  表示 {len(riv['features']):,} 本 (頂点 {riv['vtx_before']:,} → {riv['vtx_after']:,})")

    print("湖沼を走査…", flush=True)
    lak = scan_lakes(points)
    write_json(DATA / "lakes.geojson", {
        "type": "FeatureCollection",
        "features": lak["features"],
        "metadata": {
            **LAKE_LICENSE,
            "processing_method": (
                f"Douglas-Peucker(許容 {SIMPLIFY_TOL} 度 ≒ 45 m)で頂点を "
                f"{lak['vtx_before']:,} → {lak['vtx_after']:,} に間引いた。"
                "距離の計算には間引く前を使っている"
            ),
            "counts": {"polygons": lak["polygons"], "index_segments": lak["index"],
                       "vertices_before_simplify": lak["vtx_before"],
                       "vertices_after_simplify": lak["vtx_after"]},
        },
    })
    print(f"  面 {lak['polygons']:,}")

    # 点へ書き戻す
    for path in ("onsen.geojson", "control.geojson"):
        fc = json.loads((DATA / path).read_text(encoding="utf-8"))
        mine = [p for p in points if p["file"] == path]
        assert len(mine) == len(fc["features"]), f"{path} の点数が合わない"
        got_r = got_l = 0
        for p, f in zip(mine, fc["features"]):
            assert f["geometry"]["coordinates"][0] == p["lon"], "並びがずれている"
            pr = f["properties"]
            pr["distance_to_river_km"] = None if p["river_km"] is None else round(p["river_km"], 3)
            pr["nearest_river"] = None if p["river_name"] in (None, UNNAMED) else p["river_name"]
            pr["distance_to_lake_km"] = None if p["lake_km"] is None else round(p["lake_km"], 3)
            pr["nearest_lake"] = p["lake_name"]
            got_r += p["river_km"] is not None
            got_l += p["lake_km"] is not None
        fc["metadata"].setdefault("enrichment", {})
        fc["metadata"]["enrichment"]["water"] = {
            "river": RIVER_LICENSE, "lake": LAKE_LICENSE,
            "method": (f"0.05 度の格子に線分を入れ、点のまわり {MAX_RINGS} 環"
                       f"(およそ {MAX_RINGS*CELL:.1f} 度)までを見て最小距離を取る。"
                       "この範囲に見つからない点は欠測にする(埋めない)"),
            "coverage": {"river": f"{got_r}/{len(fc['features'])}",
                         "lake": f"{got_l}/{len(fc['features'])}"},
        }
        write_json(DATA / path, fc)
        print(f"{path}: 河川 {got_r}/{len(fc['features'])}  湖沼 {got_l}/{len(fc['features'])}")


if __name__ == "__main__":
    main()
