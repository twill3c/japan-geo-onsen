"""タイル座標・標高タイルのデコード・距離計算の共通実装。

ここに置いた関数は TypeScript 側(lib/)と**同じ入力に同じ出力**を返すことを
テストで照合する(SPEC G-02 / G-08)。
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "raw"
# 成果物はビルド入力の場所へ直接書く。`data/` から `public/` へ写す段を作ると、
# 写した後に元を変えたときに成果物だけが古く残る(HC-199)。写さなければその穴は開かない。
DATA = REPO / "public" / "data"

UA = "japan-geo-onsen/0.1 (educational GIS project; https://github.com/twill3c/japan-geo-onsen)"

# 国土地理院 標高タイル(PNG)の無効値。R=128,G=0,B=0 → x = 0x800000
DEM_INVALID = 0x800000


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """Web メルカトルの XYZ タイル座標(整数)を返す。"""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def lonlat_to_pixel(lon: float, lat: float, z: int) -> tuple[int, int, int, int]:
    """タイル座標とタイル内画素(0-255)を返す。"""
    n = 2**z
    fx = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    fy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    x, y = int(fx), int(fy)
    i = min(255, int((fx - x) * 256))
    j = min(255, int((fy - y) * 256))
    return x, y, i, j


def decode_dem_rgb(r: int, g: int, b: int) -> float | None:
    """地理院標高タイルの 1 画素を標高[m]にする。

    仕様: x = 2^16 R + 2^8 G + B。x < 2^23 なら h = 0.01 x、
    x > 2^23 なら h = 0.01 (x - 2^24)、x == 2^23 は無効値。
    出典: https://maps.gsi.go.jp/development/demtile.html
    """
    x = (r << 16) + (g << 8) + b
    if x == DEM_INVALID:
        return None
    if x > DEM_INVALID:
        x -= 1 << 24
    return x * 0.01


def tile_pixel_size_m(y: int, z: int, j: int) -> tuple[float, float]:
    """タイル内画素 j 行の地上寸法(東西, 南北)[m] を返す。

    メルカトルなので緯度により縮尺が変わる。傾斜計算に使う。
    """
    n = 2**z
    lat = tile_row_to_lat(y + (j + 0.5) / 256.0, z)
    earth = 2 * math.pi * 6378137.0
    res = earth / (n * 256.0)  # 赤道での 1 画素の長さ
    ground = res * math.cos(math.radians(lat))
    return ground, ground


def tile_row_to_lat(fy: float, z: int) -> float:
    n = 2**z
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * fy / n))))


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面(半径 6371.0088 km)での大円距離。"""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def vincenty_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """WGS84 楕円体上の測地線距離(Vincenty 逆解法)。haversine の対照(G-08)。"""
    a, f = 6378137.0, 1 / 298.257223563
    b = (1 - f) * a
    L = math.radians(lon2 - lon1)
    U1 = math.atan((1 - f) * math.tan(math.radians(lat1)))
    U2 = math.atan((1 - f) * math.tan(math.radians(lat2)))
    sU1, cU1, sU2, cU2 = math.sin(U1), math.cos(U1), math.sin(U2), math.cos(U2)
    lam = L
    for _ in range(200):
        sl, cl = math.sin(lam), math.cos(lam)
        ss = math.sqrt((cU2 * sl) ** 2 + (cU1 * sU2 - sU1 * cU2 * cl) ** 2)
        if ss == 0:
            return 0.0
        cs = sU1 * sU2 + cU1 * cU2 * cl
        sigma = math.atan2(ss, cs)
        sa = cU1 * cU2 * sl / ss
        c2 = 1 - sa**2
        c2m = cs - 2 * sU1 * sU2 / c2 if c2 != 0 else 0.0
        C = f / 16 * c2 * (4 + f * (4 - 3 * c2))
        prev = lam
        lam = L + (1 - C) * f * sa * (
            sigma + C * ss * (c2m + C * cs * (-1 + 2 * c2m**2))
        )
        if abs(lam - prev) < 1e-12:
            break
    u2 = c2 * (a**2 - b**2) / b**2
    A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
    dsig = B * ss * (
        c2m + B / 4 * (cs * (-1 + 2 * c2m**2) - B / 6 * c2m * (-3 + 4 * ss**2) * (-3 + 4 * c2m**2))
    )
    return b * A * (sigma - dsig) / 1000.0


def fetch(url: str, dest: Path, *, sleep: float = 0.4, binary: bool = True) -> bytes | None:
    """取得してキャッシュする。既にあれば触らない(外部への過剰アクセスを避ける — 設計書 §44)。"""
    if dest.exists():
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    dest.write_bytes(body)
    time.sleep(sleep)
    return body


def point_segment_distance_km(
    plon: float, plat: float,
    alon: float, alat: float,
    blon: float, blat: float,
) -> float:
    """点と線分の距離[km]。

    球面上で厳密に解くと重いので、**点のまわりで局所平面に落として**解く。
    経度は cos(緯度) で縮め、1 度あたりの長さを緯度に依らない定数として扱う。
    河川の 1 区間(数 km〜数十 km)の範囲では、刻み方式の大円距離と 0.5% 以内で
    一致することをテストで確かめている(SPEC G-09)。
    """
    # 1 度あたりの長さ。**haversine と同じ球**を使う。
    # ここで楕円体の子午線長(緯度 36 度で 110.96 km/度)を使うと、端点に落ちる場合に
    # 返す haversine(球で 111.19 km/度)と 0.2% 食い違い、同じ関数の中で
    # 二つの地球が混ざる。距離の基準はプロジェクト全体で球に揃える(G-08 と同じ球)。
    lat0 = math.radians(plat)
    km_per_deg_lat = 6371.0088 * math.pi / 180.0
    km_per_deg_lon = km_per_deg_lat * math.cos(lat0)

    ax = (alon - plon) * km_per_deg_lon
    ay = (alat - plat) * km_per_deg_lat
    bx = (blon - plon) * km_per_deg_lon
    by = (blat - plat) * km_per_deg_lat

    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0.0:  # 退化した線分 = ただの点。近似せず大円距離を返す
        return haversine_km(plon, plat, alon, alat)
    # 点(原点)から線分 AB への射影パラメータ
    t = -(ax * dx + ay * dy) / denom
    # 垂線の足が線分の外に落ちるときは端点との距離であり、これも近似しない。
    # 河川の区間に対しては**この場合が大半**なので、ここを厳密にしておく意味は大きい。
    if t <= 0.0:
        return haversine_km(plon, plat, alon, alat)
    if t >= 1.0:
        return haversine_km(plon, plat, blon, blat)
    return math.hypot(ax + dx * t, ay + dy * t)


def point_polyline_distance_km(plon: float, plat: float, line) -> float | None:
    """点と折れ線の距離[km]。頂点が無ければ None、1 点だけならその点までの距離。"""
    pts = list(line)
    if not pts:
        return None
    if len(pts) == 1:
        return point_segment_distance_km(plon, plat, pts[0][0], pts[0][1], pts[0][0], pts[0][1])
    best = float("inf")
    for i in range(len(pts) - 1):
        d = point_segment_distance_km(plon, plat, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if d < best:
            best = d
    return best


P12_ZIP = RAW / "ksj" / "P12-14_GML.zip"
P12_DIR = RAW / "ksj" / "P12"


def ensure_p12() -> Path:
    """P12 のシェープファイルを使える状態にして、その置き場を返す。

    リポジトリに入れてあるのは配布された zip そのものだけである。展開物を
    コミットすると、zip と展開物のどちらが正かが曖昧になる。**配布形を正とし、
    使うときに展開する**(HC-139 と同じ考え方)。
    """
    if not P12_DIR.exists() or not any(P12_DIR.glob("P12a-14_*.shp")):
        if not P12_ZIP.exists():
            raise SystemExit(
                f"{P12_ZIP} が無い。次で取得すること:\n"
                "  curl -L -o raw/ksj/P12-14_GML.zip "
                "https://nlftp.mlit.go.jp/ksj/gml/data/P12/P12-14/P12-14_GML.zip"
            )
        import zipfile

        P12_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(P12_ZIP) as z:
            z.extractall(P12_DIR)
    return P12_DIR


def write_json(path: Path, obj, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.write("\n")
