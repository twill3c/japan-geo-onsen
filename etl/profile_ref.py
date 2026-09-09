"""地形断面(標高プロファイル)の参照実装(設計書 §56 / SPEC G-14)。

出荷するのはブラウザ側の TypeScript(lib/profile.ts)である。ここはその**照合相手**で、
同じ入力に同じ出力を返すことを tests-js/profile.test.ts が実タイルで確かめる
(標高タイルの解読と同じ二実装照合の形 —— SPEC G-02)。

照合が効くのは、断面の誤りが**静かに**出るからである。画素の添字を 1 つ取り違えても、
南北を裏返しても、線はそれらしい形で描かれてしまう。数を突き合わせる相手が要る。

## 何をどう決めているか

- **点の並べ方**: A→B を大円上で等間隔に刻む(球面線形補間)。平面で刻むと
  緯度の高い所で間隔が歪む
- **距離**: 球(半径 6371.0088 km)の大円距離。etl/common.py の haversine_km と同じ球
- **標高の引き方**: その点が入る画素の値を**そのまま**使う(最近傍)。
  周りの画素と混ぜない —— 混ぜると、元データに無い標高が図に出る
  (等高線で欠測セルを補間しないのと同じ理由)
- **欠測**: 標高タイルの無効値 x=2^23 と、タイルそのものが無い場所は null のまま
"""
from __future__ import annotations

import math

R_KM = 6371.0088


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面(半径 6371.0088 km)での大円距離。etl/common.py と同じ式。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(a)))


def slerp(lon1: float, lat1: float, lon2: float, lat2: float, t: float) -> tuple[float, float]:
    """大円上を A から B へ割合 t だけ進んだ点(球面線形補間)。"""
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2, l2 = math.radians(lat2), math.radians(lon2)
    # 2 点間の角距離
    d = 2 * math.asin(min(1.0, math.sqrt(
        math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    )))
    if d == 0.0:
        return lon1, lat1
    a = math.sin((1 - t) * d) / math.sin(d)
    b = math.sin(t * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y)))


def world_pixel(lon: float, lat: float, z: int, tile_size: int = 256) -> tuple[float, float]:
    """Web メルカトルの世界画素座標(小数)。"""
    n = 2 ** z * tile_size
    px = (lon + 180.0) / 360.0 * n
    rad = math.radians(lat)
    py = (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n
    return px, py


def pixel_resolution_m(z: int, lat: float, tile_size: int = 256) -> float:
    """その緯度・その段の 1 画素が地上で何 m か。"""
    return 2 * math.pi * R_KM * 1000 * math.cos(math.radians(lat)) / (2 ** z * tile_size)


def sample_positions(
    lon1: float, lat1: float, lon2: float, lat2: float, count: int
) -> list[dict]:
    """A→B を count 点に刻む。両端を含む。"""
    if count < 2:
        raise ValueError(f"断面の点は 2 点以上でなければならない: {count}")
    total = haversine_km(lon1, lat1, lon2, lat2)
    out = []
    for k in range(count):
        t = k / (count - 1)
        lon, lat = slerp(lon1, lat1, lon2, lat2, t)
        out.append({"t": t, "lon": lon, "lat": lat, "distance_km": total * t})
    return out


def profile(
    lon1: float, lat1: float, lon2: float, lat2: float, count: int, z: int,
    lookup,
) -> list[dict]:
    """断面。lookup(tile_x, tile_y, i, j) が標高[m] または None を返す。"""
    out = []
    for p in sample_positions(lon1, lat1, lon2, lat2, count):
        px, py = world_pixel(p["lon"], p["lat"], z)
        tx, ty = int(px // 256), int(py // 256)
        i, j = int(px) % 256, int(py) % 256
        out.append({**p, "tile_x": tx, "tile_y": ty, "i": i, "j": j,
                    "elevation": lookup(tx, ty, i, j)})
    return out
