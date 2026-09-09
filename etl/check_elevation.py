"""断面が読む標高を、**外部の権威**と突き合わせる(SPEC G-15 / 設計書 §56)。

二実装照合(TypeScript ↔ Python 参照実装)が言えるのは「両方が同じ答えを出す」までで、
**その標高が正しいか**は言えない。画素の添字を両方で同じだけずらしていれば、
二つとも仲良く間違う。そこで別の出所を当てる。

- **地理院の標高 API**(`getelevation.php`)。同じ国土地理院だが、**別の経路・別の元データ**
  (可能なら DEM5A、無ければ DEM10B)から標高を返す。鍵は要らない(設計書 §68)
- **山頂の公表標高**。座標も標高も **Wikidata(CC0)から取る**。

  最初この山の座標を記憶で書いて、北岳が公表値より 43 m 低く出た。API も同じ値を
  返していたので、ずれていたのはタイルではなく**私の書いた座標**だった(山頂でない点を
  山頂と呼んでいた)。推測した値を検算の材料にしない(設計書 §71)。
  なお山頂の比較は座標の精度と標高の精度が混ざるので、点そのものだけでなく
  **周囲 ±25 画素の最大値**も見る —— 公表標高と比べるべきはこちらである

差が出ること自体は異常ではない。標高タイル(dem_png)は DEM10B 相当、API は場所により
DEM5A で、格子の刻みも違う。ここで捕まえたいのは**桁の違う食い違い**
—— 画素の取り違え、南北の裏返し、経度緯度の取り違え。これらは数十〜数百 m の差になる。

出力は logs/elevation_check.json。結果は TEST_SPEC.md に書き写す。
"""
from __future__ import annotations

import io
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from etl.common import RAW, REPO, UA, decode_dem_rgb, fetch
from etl.profile_ref import world_pixel

DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"
API = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php?lon={lon}&lat={lat}&outtype=JSON"
OUT = REPO / "logs" / "elevation_check.json"
PEAKS_RAW = RAW / "wikidata" / "peaks_query_result.json"
Z = 14
SEED = 20260907
PEAK_BOX_PX = 25   # 山頂を探す範囲(±画素)。z14・北緯 36 度で片側 約 190 m

# 山の座標と標高は Wikidata(CC0)から取る。**名前だけ**をこちらで指定し、
# Q 番号は書かない(番号を記憶で書けば、また推測を持ち込むことになる)。
PEAK_NAMES = ["富士山", "北岳"]
PEAK_SPARQL = """
SELECT ?x ?xLabel ?coord ?elev WHERE {
  VALUES ?name { "富士山"@ja "北岳"@ja }
  ?x rdfs:label ?name .
  ?x wdt:P17 wd:Q17 .
  ?x wdt:P625 ?coord .
  ?x wdt:P2044 ?elev .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
# 無作為点はデモ地域(山梨・長野・静岡のあたり)から取る
BOX = {"west": 137.9, "east": 138.9, "south": 35.2, "north": 36.3}
N_RANDOM = 24


def fetch_peaks() -> list[dict]:
    """山の座標と公表標高を Wikidata から取る。既に取ってあれば触らない。"""
    if PEAKS_RAW.exists():
        doc = json.loads(PEAKS_RAW.read_text(encoding="utf-8"))
    else:
        import urllib.parse
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
            {"query": PEAK_SPARQL, "format": "json"})
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            doc = json.load(r)
        PEAKS_RAW.parent.mkdir(parents=True, exist_ok=True)
        PEAKS_RAW.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    cands: list[dict] = []
    for b in doc["results"]["bindings"]:
        lon, lat = b["coord"]["value"].replace("Point(", "").replace(")", "").split()
        cands.append({
            "name": b["xLabel"]["value"],
            "qid": b["x"]["value"].rsplit("/", 1)[-1],
            "lon": float(lon),
            "lat": float(lat),
            "published_m": float(b["elev"]["value"]),
        })

    # 同じ名前の項目が複数返る(「富士山」は茨城 152 m・栃木 160 m の山も同名で在る)。
    # ここでの目当ては**高いほうの標高で目盛りを確かめる**ことなので、
    # 名前ごとに標高が最大の項目を採り、落とした候補も記録に残す(選び方を隠さない)。
    out = []
    for name in PEAK_NAMES:
        same = [c for c in cands if c["name"] == name]
        if not same:
            raise SystemExit(f"Wikidata から取れなかった山がある: {name}")
        same.sort(key=lambda c: c["published_m"], reverse=True)
        chosen = dict(same[0])
        chosen["rejected"] = [{"qid": c["qid"], "published_m": c["published_m"]} for c in same[1:]]
        out.append(chosen)
    return out


def tile_max(lon: float, lat: float, radius_px: int) -> float | None:
    """その点の周り ±radius_px 画素の最大標高。公表された山頂標高と比べる相手。"""
    px, py = world_pixel(lon, lat, Z)
    best: float | None = None
    for dj in range(-radius_px, radius_px + 1):
        for di in range(-radius_px, radius_px + 1):
            v = pixel_at(px + di, py + dj)
            if v is not None and (best is None or v > best):
                best = v
    return best


def pixel_at(px: float, py: float) -> float | None:
    x, y = int(px // 256), int(py // 256)
    i, j = int(px) % 256, int(py) % 256
    dest = RAW / "gsi" / "dem_png" / str(Z) / str(x) / f"{y}.png"
    body = fetch(DEM_URL.format(z=Z, x=x, y=y), dest, sleep=0.15)
    if body is None:
        return None
    key = (x, y)
    grid = _grids.get(key)
    if grid is None:
        im = Image.open(io.BytesIO(body)).convert("RGB")
        pxl = im.load()
        grid = [[decode_dem_rgb(*pxl[a, b]) for a in range(256)] for b in range(256)]
        _grids[key] = grid
    return grid[j][i]


_grids: dict[tuple[int, int], list[list[float | None]]] = {}


def tile_elevation(lon: float, lat: float) -> float | None:
    """断面と同じ道筋で標高を引く(profile_ref の画素計算をそのまま使う)。"""
    px, py = world_pixel(lon, lat, Z)
    x, y = int(px // 256), int(py // 256)
    i, j = int(px) % 256, int(py) % 256
    dest = RAW / "gsi" / "dem_png" / str(Z) / str(x) / f"{y}.png"
    body = fetch(DEM_URL.format(z=Z, x=x, y=y), dest, sleep=0.15)
    if body is None:
        return None
    im = Image.open(io.BytesIO(body)).convert("RGB")
    return decode_dem_rgb(*im.load()[i, j])


def api_elevation(lon: float, lat: float) -> tuple[float | None, str]:
    req = urllib.request.Request(API.format(lon=f"{lon:.7f}", lat=f"{lat:.7f}"),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    time.sleep(0.5)   # 外部への過剰アクセスを避ける(設計書 §44)
    h = d.get("elevation")
    src = str(d.get("hsrc", ""))
    if h in (None, "-----"):
        return None, src
    return float(h), src


def main() -> None:
    rng = random.Random(SEED)
    peaks = fetch_peaks()
    points = [dict(p) for p in peaks]
    for _ in range(N_RANDOM):
        points.append({
            "name": "無作為点",
            "lon": rng.uniform(BOX["west"], BOX["east"]),
            "lat": rng.uniform(BOX["south"], BOX["north"]),
            "published_m": None,
        })

    rows = []
    for p in points:
        tile = tile_elevation(p["lon"], p["lat"])
        api, src = api_elevation(p["lon"], p["lat"])
        peak_max = tile_max(p["lon"], p["lat"], PEAK_BOX_PX) if p["published_m"] else None
        rows.append({
            **p,
            "tile_m": tile,
            "tile_max_m": peak_max,
            "api_m": api,
            "api_source": src,
            "diff_m": None if (tile is None or api is None) else round(tile - api, 3),
        })
        extra = f"  周囲最大 {peak_max}(公表 {p['published_m']})" if peak_max is not None else ""
        print(f"  {p['name']:<12} タイル {tile}  API {api} ({src})  差 {rows[-1]['diff_m']}{extra}")

    diffs = sorted(abs(r["diff_m"]) for r in rows if r["diff_m"] is not None)
    n = len(diffs)
    summary = {
        "z": Z,
        "points": len(rows),
        "compared": n,
        "median_abs_diff_m": diffs[n // 2] if n else None,
        "p90_abs_diff_m": diffs[int(n * 0.9)] if n else None,
        "max_abs_diff_m": diffs[-1] if n else None,
        "peaks": [
            {
                "name": r["name"], "qid": r.get("qid"),
                "published_m": r["published_m"],
                "tile_m": r["tile_m"],
                "tile_max_m": r["tile_max_m"],
                "radius_px": PEAK_BOX_PX,
                # 公表された山頂標高と比べるべきは、点そのものではなく周囲の最大値
                "diff_from_published_m": None if r["tile_max_m"] is None
                else round(r["tile_max_m"] - r["published_m"], 2),
            }
            for r in rows if r["published_m"] is not None
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
