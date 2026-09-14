"""温泉のまわり 5/10/25/50 km に何があるかを数える(設計書 §56「周辺環境分析」)。

## 何を数えるか / 数えないか

数えるのは、**手元のデータで正確に数え切れるもの**だけである。

| 数える | 出所 | 数え方 |
|---|---|---|
| 活火山 | 気象庁(111) | 中心からの大円距離 ≤ r |
| 温泉(国土数値情報) | P12(1,320) | 同上。**自分自身は除く** |
| 温泉(Wikidata) | Wikidata(1,477) | 同上。自分自身は除く。出所が違うので別の欄 |
| 湖沼 | 国土数値情報 W09(生データの面) | **縁まで**の距離 ≤ r(中心で測ると大きい湖が遠く出る) |
| 植生自然度 | 環境省 第5回基礎調査(3 次メッシュ) | 中心が半径内に入るメッシュを、統計ページと同じ 6 帯に畳む |

**河川は数えない。** 全国 286,437 区間について半径内の本数を全点で数えると、
一度踏んだ「厳密な距離を全候補に呼んで CPU 51 分」の穴に戻る。最寄りの距離は既に持っている。
**標高の起伏も数えない。** 半径 50 km を標高タイル z14 で覆うと 1 点あたり 1 億画素を超える。

## 計算の形

半径ごとに探し直さない。**50 km 以内の候補を一度だけ集めて距離を持ち、4 つの半径で数える。**
候補の集め方(格子)は近道なので、答えが総当たりと完全に一致することを
tests/test_surroundings.py が確かめる(G-19)。

## 配り方

温泉の点ファイルには混ぜない。**点を開いたときに初めて読む別ファイル**にする
(public/data/surroundings/<層>.json)。起動時に読むデータを増やさない —— 既定で消えている
層を先読みして 1.8 MB 余計に配っていた失敗(loop_009)と同じ理由である。
"""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_stats import _sizendo_band
from etl.build_vegetation import load_mesh, load_tables
from etl.build_water import open_shp_in_zip
from etl.common import DATA, RAW, haversine_km, point_segment_distance_km, write_json
from etl.mesh import MESH3_DLAT, MESH3_DLON, mesh3_center

RADII_KM = (5, 10, 25, 50)
MAX_KM = max(RADII_KM)
# 対象の層(点ファイル名 → 出力名)
TARGETS = {
    "onsen.geojson": "onsen",
    "onsen_wikidata.geojson": "onsen_wikidata",
    "onsen_facility.geojson": "onsen_facility",
    "onsen_wikipedia.geojson": "onsen_wikipedia",
}
OUT_DIR = DATA / "surroundings"
KM_PER_DEG_LAT = 6371.0088 * math.pi / 180.0

# 植生の帯は統計ページと**同じ関数**で畳む(規則を二度書かない)
BANDS = [
    "1〜2(市街地・農耕地)",
    "3〜5(樹園地・二次草原)",
    "6(植林地)",
    "7〜8(二次林)",
    "9〜10(自然林・自然草原)",
    "その他(裸地・水域)",
]
# 1 半径ぶんの並び。配る量を抑えるため辞書でなく配列にし、並びをここで固定する
COLUMNS = ["volcanoes", "onsen_ksj", "onsen_wikidata", "lakes", "vegetation_meshes", *BANDS]


def _box(lon: float, lat: float, km: float) -> tuple[float, float]:
    """半径 km を覆う緯度幅・経度幅(度)。**少し広め**に取る(漏れより余分のほうが安全)。"""
    dlat = km / KM_PER_DEG_LAT * 1.01
    # 半径の端では緯度が動いて経度 1 度の長さも変わるので、極に近い側の緯度で測る
    far = min(89.9, abs(lat) + dlat)
    dlon = km / max(1e-9, KM_PER_DEG_LAT * math.cos(math.radians(far))) * 1.01
    return dlat, dlon


class PointGrid:
    """点を 0.5 度の格子に入れ、半径内の点を距離つきで返す。"""

    CELL = 0.5

    def __init__(self, items: list[tuple[float, float, str]]) -> None:
        self.items = items
        self.cells: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
        for k, (lon, lat, _) in enumerate(items):
            self.cells[(math.floor(lat / self.CELL), math.floor(lon / self.CELL))].append(k)

    def within(self, lon: float, lat: float, km: float) -> list[tuple[int, float]]:
        dlat, dlon = _box(lon, lat, km)
        out = []
        for j in range(math.floor((lat - dlat) / self.CELL), math.floor((lat + dlat) / self.CELL) + 1):
            for i in range(math.floor((lon - dlon) / self.CELL), math.floor((lon + dlon) / self.CELL) + 1):
                for k in self.cells.get((j, i), ()):
                    plon, plat, _ = self.items[k]
                    d = haversine_km(lon, lat, plon, plat)
                    if d <= km:
                        out.append((k, d))
        return out


class MeshIndex:
    """3 次メッシュを整数の (行, 列) で引く。メッシュは規則格子なので整数で歩ける。"""

    def __init__(self, mesh: dict[str, str]) -> None:
        self.by_rc: dict[tuple[int, int], str] = {}
        for code, gun in mesh.items():
            lon, lat = mesh3_center(code)
            self.by_rc[(round(lat / MESH3_DLAT - 0.5), round(lon / MESH3_DLON - 0.5))] = gun

    @staticmethod
    def center(r: int, c: int) -> tuple[float, float]:
        return (c + 0.5) * MESH3_DLON, (r + 0.5) * MESH3_DLAT

    def within(self, lon: float, lat: float, km: float) -> list[tuple[str, float]]:
        dlat, dlon = _box(lon, lat, km)
        out = []
        for r in range(math.floor((lat - dlat) / MESH3_DLAT), math.ceil((lat + dlat) / MESH3_DLAT) + 1):
            for c in range(math.floor((lon - dlon) / MESH3_DLON), math.ceil((lon + dlon) / MESH3_DLON) + 1):
                gun = self.by_rc.get((r, c))
                if gun is None:
                    continue
                clon, clat = self.center(r, c)
                d = haversine_km(lon, lat, clon, clat)
                if d <= km:
                    out.append((gun, d))
        return out


def load_lakes() -> list[list[list[tuple[float, float]]]]:
    """湖沼の環(生データ。表示用に間引く前のもの)。"""
    r = open_shp_in_zip(str(RAW / "ksj" / "W09" / "W09-05_GML.zip"), "Lake")
    if r is None:
        raise SystemExit("W09 の Lake が無い")
    lakes = []
    for sr in r.iterShapeRecords():
        pts = sr.shape.points
        if len(pts) < 3:
            continue
        parts = list(sr.shape.parts) + [len(pts)]
        rings = [pts[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]
        rings = [ring for ring in rings if len(ring) >= 3]
        if rings:
            lakes.append(rings)
    return lakes


def lake_distance_km(lon: float, lat: float, rings) -> float:
    """面の縁までの最短距離。"""
    best = math.inf
    for ring in rings:
        n = len(ring)
        for k in range(n):
            a, b = ring[k], ring[(k + 1) % n]
            d = point_segment_distance_km(lon, lat, a[0], a[1], b[0], b[1])
            if d < best:
                best = d
    return best


def lake_bounds(rings) -> tuple[float, float, float, float]:
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return min(xs), min(ys), max(xs), max(ys)


class Context:
    """数える相手をまとめて持つ。テストからは小さな相手を差し込める。"""

    def __init__(self, volcanoes: PointGrid, ksj: PointGrid, wikidata: PointGrid,
                 lakes: list, mesh: MeshIndex, gunraku: dict) -> None:
        self.volcanoes = volcanoes
        self.ksj = ksj
        self.wikidata = wikidata
        self.lakes = lakes
        self.lake_boxes = [lake_bounds(r) for r in lakes]
        self.mesh = mesh
        self.gunraku = gunraku


def surroundings(lon: float, lat: float, ctx: Context, self_id: str | None) -> list[list[int]]:
    """半径ごとの数を、COLUMNS の並びの配列で返す(RADII_KM の順)。"""
    vol = [d for _, d in ctx.volcanoes.within(lon, lat, MAX_KM)]
    # 自分自身は数えない(同じ層の中に自分が居る)
    ksj = [d for k, d in ctx.ksj.within(lon, lat, MAX_KM) if ctx.ksj.items[k][2] != self_id]
    wd = [d for k, d in ctx.wikidata.within(lon, lat, MAX_KM) if ctx.wikidata.items[k][2] != self_id]

    dlat, dlon = _box(lon, lat, MAX_KM)
    lake = []
    for rings, (x0, y0, x1, y1) in zip(ctx.lakes, ctx.lake_boxes):
        if x1 < lon - dlon or x0 > lon + dlon or y1 < lat - dlat or y0 > lat + dlat:
            continue
        d = lake_distance_km(lon, lat, rings)
        if d <= MAX_KM:
            lake.append(d)

    veg = []
    for gun, d in ctx.mesh.within(lon, lat, MAX_KM):
        g = ctx.gunraku.get(gun)
        if g is not None:
            veg.append((_sizendo_band(g["sizendo"]), d))

    out = []
    for km in RADII_KM:
        bands = collections.Counter(b for b, d in veg if d <= km)
        out.append([
            sum(1 for d in vol if d <= km),
            sum(1 for d in ksj if d <= km),
            sum(1 for d in wd if d <= km),
            sum(1 for d in lake if d <= km),
            sum(1 for _, d in veg if d <= km),
            *[bands.get(b, 0) for b in BANDS],
        ])
    return out


def load_context() -> Context:
    def grid_of(path: str) -> PointGrid:
        fc = json.loads((DATA / path).read_text(encoding="utf-8"))
        return PointGrid([
            (f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
             str(f["properties"].get("onsen_id") or f["properties"].get("name") or i))
            for i, f in enumerate(fc["features"])
        ])

    gunraku, _, _ = load_tables()
    return Context(
        volcanoes=grid_of("volcanoes.geojson"),
        ksj=grid_of("onsen.geojson"),
        wikidata=grid_of("onsen_wikidata.geojson"),
        lakes=load_lakes(),
        mesh=MeshIndex(load_mesh()),
        gunraku=gunraku,
    )


def main() -> None:
    ctx = load_context()
    print(f"火山 {len(ctx.volcanoes.items)} / P12 {len(ctx.ksj.items)} / "
          f"Wikidata {len(ctx.wikidata.items)} / 湖沼 {len(ctx.lakes)} / メッシュ {len(ctx.mesh.by_rc):,}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, name in TARGETS.items():
        fc = json.loads((DATA / path).read_text(encoding="utf-8"))
        rows: dict[str, list[list[int]]] = {}
        for n, f in enumerate(fc["features"], 1):
            lon, lat = f["geometry"]["coordinates"]
            oid = str(f["properties"]["onsen_id"])
            rows[oid] = surroundings(lon, lat, ctx, self_id=oid)
            if n % 250 == 0:
                print(f"  {name}: {n}/{len(fc['features'])}", flush=True)
        write_json(OUT_DIR / f"{name}.json", {
            "radii_km": list(RADII_KM),
            "columns": COLUMNS,
            "method": (
                "中心から大円距離(球 6371.0088 km)で半径内を数えた。自分自身は除く。"
                "湖沼は生データの面の縁までの距離、植生はメッシュ中心が半径内に入るもの。"
                "河川と標高の起伏は数えていない(計算量の理由)"
            ),
            "sources": ["気象庁 活火山", "国土数値情報 P12", "Wikidata(CC0)",
                        "国土数値情報 W09 湖沼", "環境省 第5回自然環境保全基礎調査 植生"],
            "rows": rows,
        })
        print(f"{name}: {len(rows)} 点", flush=True)


if __name__ == "__main__":
    main()
