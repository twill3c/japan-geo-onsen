"""標準地域メッシュ(3 次メッシュ)と緯度経度の相互変換。

植生データはメッシュコードでしか位置を持たないので、ここが要になる。
検算は tests/test_mesh.py に置いた(往復・外部権威・境界の接合)。

3 次メッシュ(約 1 km)のコードは 8 桁:

    1〜2 桁  緯度 × 1.5 の整数部        1 次メッシュの南端 = この値 / 1.5 度
    3〜4 桁  経度 − 100 の整数部        1 次メッシュの西端 = 100 + この値 度
    5 桁     1 次を南北 8 等分した番号   0〜7
    6 桁     1 次を東西 8 等分した番号   0〜7
    7 桁     2 次を南北 10 等分した番号  0〜9
    8 桁     2 次を東西 10 等分した番号  0〜9

1 次メッシュは 緯度 40 分 × 経度 1 度。3 次はその 1/80 なので
緯度 30 秒 × 経度 45 秒 になる。
"""
from __future__ import annotations

# 1 次メッシュの大きさ(度)
MESH1_DLAT = 2.0 / 3.0     # 40 分
MESH1_DLON = 1.0
# 3 次メッシュの大きさ(度)。1 次の 1/80
MESH3_DLAT = MESH1_DLAT / 80.0   # 30 秒
MESH3_DLON = MESH1_DLON / 80.0   # 45 秒


def _parse(code: str) -> tuple[int, int, int, int, int, int]:
    if not isinstance(code, str) or len(code) != 8 or not code.isdigit():
        raise ValueError(f"3 次メッシュコードは 8 桁の数字でなければならない: {code!r}")
    p = int(code[0:2])
    q = int(code[2:4])
    r = int(code[4])
    s = int(code[5])
    t = int(code[6])
    u = int(code[7])
    # 2 次の区画番号は 0〜7(1 次を 8 等分するため)。範囲外は黙って通さない
    if r > 7 or s > 7:
        raise ValueError(f"2 次区画の番号が範囲外(0〜7): {code!r}")
    return p, q, r, s, t, u


def mesh3_bounds(code: str) -> tuple[float, float, float, float]:
    """(west, south, east, north) を度で返す。"""
    p, q, r, s, t, u = _parse(code)
    south = p / 1.5 + r * (MESH1_DLAT / 8) + t * MESH3_DLAT
    west = 100.0 + q + s * (MESH1_DLON / 8) + u * MESH3_DLON
    return west, south, west + MESH3_DLON, south + MESH3_DLAT


def mesh3_center(code: str) -> tuple[float, float]:
    """(lon, lat) の中心を返す。"""
    w, s, e, n = mesh3_bounds(code)
    return (w + e) / 2.0, (s + n) / 2.0


def point_to_mesh3(lon: float, lat: float) -> str:
    """緯度経度から 3 次メッシュコードを作る。"""
    p = int(lat * 1.5)
    a = lat * 1.5 - p
    r = int(a * 8)
    b = a * 8 - r
    t = int(b * 10)

    q = int(lon) - 100
    c = lon - int(lon)
    s = int(c * 8)
    d = c * 8 - s
    u = int(d * 10)
    return f"{p:02d}{q:02d}{r}{s}{t}{u}"


def mesh3_polygon(code: str) -> list[list[float]]:
    """GeoJSON のポリゴン用に、閉じた 5 点の環を返す。"""
    w, s, e, n = mesh3_bounds(code)
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]
