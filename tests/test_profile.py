"""地形断面の参照実装の検算(SPEC G-14)。

この参照実装(etl/profile_ref.py)は、出荷する TypeScript(lib/profile.ts)の
**照合相手**である。照合相手が間違っていれば、二つ揃って間違う。だからここでは
参照実装そのものを、別の出所と突き合わせる。

- 画素の位置は、先に書いてあった `etl/common.lonlat_to_pixel`(温泉点の標高付けで
  使っている**別の実装**)と一致すること
- 距離は `etl/common.haversine_km`、および楕円体の `vincenty_km` と近いこと
- 大円上の刻みは、区間の和が全長に戻ること
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import haversine_km as common_haversine
from etl.common import lonlat_to_pixel, vincenty_km
from etl.profile_ref import (
    R_KM, haversine_km, pixel_resolution_m, sample_positions, slerp, world_pixel,
)

pytestmark = pytest.mark.unit

# 日本のあたりから無作為に点を取る
BOX = (128.0, 30.0, 146.0, 45.0)
SEED = 20260907


def _points(n: int) -> list[tuple[float, float]]:
    rng = random.Random(SEED)
    return [(rng.uniform(BOX[0], BOX[2]), rng.uniform(BOX[1], BOX[3])) for _ in range(n)]


def test_距離が_common_py_と同じ():
    for lon, lat in _points(50):
        assert haversine_km(139.0, 35.0, lon, lat) == pytest.approx(
            common_haversine(139.0, 35.0, lon, lat), rel=1e-12)


def test_距離が楕円体の測地線と_05パーセント以内():
    """球と楕円体は原理的に違う。桁が合っていることだけを言う。"""
    for lon, lat in _points(30):
        a = haversine_km(139.0, 35.0, lon, lat)
        b = vincenty_km(139.0, 35.0, lon, lat)
        assert abs(a - b) / b < 0.005, (lon, lat, a, b)


@pytest.mark.parametrize("z", [8, 11, 14])
def test_画素の位置が別実装と一致する(z):
    """出所: etl/common.lonlat_to_pixel(温泉点の標高付けで使っている実装)。"""
    for lon, lat in _points(200):
        px, py = world_pixel(lon, lat, z)
        got = (int(px // 256), int(py // 256), int(px) % 256, int(py) % 256)
        assert got == lonlat_to_pixel(lon, lat, z), (lon, lat, z)


def test_1画素の大きさが赤道の全周から導ける():
    circumference = 2 * math.pi * R_KM * 1000
    assert pixel_resolution_m(0, 0) == pytest.approx(circumference / 256, rel=1e-12)
    assert pixel_resolution_m(14, 35) == pytest.approx(
        circumference * math.cos(math.radians(35)) / (2 ** 14 * 256), rel=1e-12)


def test_大円の両端と中点():
    assert slerp(138.0, 35.0, 139.0, 36.0, 0.0) == pytest.approx((138.0, 35.0), abs=1e-9)
    assert slerp(138.0, 35.0, 139.0, 36.0, 1.0) == pytest.approx((139.0, 36.0), abs=1e-9)
    mlon, mlat = slerp(138.0, 35.0, 140.0, 37.0, 0.5)
    d1 = haversine_km(138.0, 35.0, mlon, mlat)
    d2 = haversine_km(mlon, mlat, 140.0, 37.0)
    assert d1 == pytest.approx(d2, rel=1e-9)


def test_刻んだ区間の和が全長に戻る():
    pts = sample_positions(138.0, 35.0, 140.5, 37.5, 200)
    total = haversine_km(138.0, 35.0, 140.5, 37.5)
    s = sum(
        haversine_km(pts[k - 1]["lon"], pts[k - 1]["lat"], pts[k]["lon"], pts[k]["lat"])
        for k in range(1, len(pts))
    )
    assert s == pytest.approx(total, rel=1e-9)
    assert pts[-1]["distance_km"] == pytest.approx(total, rel=1e-12)


def test_平面で刻んだ場合とは実際に違う():
    """球面で刻む意味があることの確認。差が 0 なら、この工夫は何もしていない。"""
    lon1, lat1, lon2, lat2 = 130.0, 32.0, 145.0, 44.0
    mlon, mlat = slerp(lon1, lat1, lon2, lat2, 0.5)
    flat = ((lon1 + lon2) / 2, (lat1 + lat2) / 2)
    assert haversine_km(mlon, mlat, flat[0], flat[1]) > 1.0


def test_点が2未満なら例外():
    with pytest.raises(ValueError):
        sample_positions(138.0, 35.0, 139.0, 36.0, 1)


def _fixture_tile():
    """実タイル 1 枚(tests-js/fixtures/dem_tiles.json に入っている)を引ける形で返す。"""
    import base64
    import io as _io
    import json

    from PIL import Image

    from etl.common import REPO, decode_dem_rgb

    doc = json.loads((REPO / "tests-js" / "fixtures" / "dem_tiles.json").read_text(encoding="utf-8"))
    t = next(x for x in doc["tiles"] if x["path"] == "14/14463/6387")
    z, x, y = (int(v) for v in t["path"].split("/"))
    im = Image.open(_io.BytesIO(base64.b64decode(t["png_base64"]))).convert("RGB")
    px = im.load()

    def lookup(tx, ty, i, j):
        if (tx, ty) != (x, y):
            return None
        return decode_dem_rgb(*px[i, j])

    return z, x, y, lookup


def _gain(pts):
    g = 0.0
    for k in range(1, len(pts)):
        a, b = pts[k - 1]["elevation"], pts[k]["elevation"]
        if a is None or b is None:
            continue
        if b > a:
            g += b - a
    return g


def test_上り累積は刻みが細かいほど大きくなる():
    """画面に書いた但し書きの検算。

    「上り・下りの合計は刻みの細かさで変わる」と断面図に書いている。書いた以上は測る。

    実測(八ヶ岳の実タイル z14 を対角に 2.723 km・1 画素 7.64 m):

        刻み 143.3 m → 330.50 m
        刻み  55.6 m → 354.29 m
        刻み  13.7 m → 366.79 m
        刻み   6.8 m → 373.05 m   ← 1 画素とほぼ同じ細かさ
        刻み   3.4 m → 375.40 m
        刻み   0.9 m → 383.95 m

    **単調に増えるが、1 画素より細かく刻んでも大きくは増えない。**
    同じ画素を何度も読むだけだからである。出荷側も 1 画素より細かくは刻まない。

    起伏(最大−最小)のほうは 100 点(刻み 27.5 m)以降ほぼ動かない。
    ただし **20 点(刻み 143 m)では 7% 低く出る** —— 山も谷も飛ばすからである。
    「起伏は刻みに依らない」と無条件には言えない。長い線では点数の上限
    (MAX_SAMPLES)に当たって 1 画素より粗く刻むので、画面にもそう書く。
    """
    from etl.profile_ref import profile

    z, tx, ty, lookup = _fixture_tile()
    # タイルの内側を対角に横切る線(make_profile_fixture.py と同じ取り方)
    import math

    n = 2 ** z
    west = tx / n * 360.0 - 180.0
    east = (tx + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / n))))
    mx, my = (east - west) / 128, (north - south) / 128
    a = (west + mx, south + my)
    b = (east - mx, north - my)

    counts = (20, 50, 100, 200, 400, 800)
    gains, reliefs = [], []
    for count in counts:
        pts = profile(a[0], a[1], b[0], b[1], count, z, lookup)
        vals = [p["elevation"] for p in pts if p["elevation"] is not None]
        gains.append(_gain(pts))
        reliefs.append(max(vals) - min(vals))

    # 単調に増える(細かく刻むほど、拾う小さな上下が増える)
    assert gains == sorted(gains), gains
    # 粗い刻みでは目に見えて小さくなる(画面の但し書きが空文でないこと)
    assert gains[0] < gains[-1] * 0.95, gains
    # ただし 1 画素より細かく刻んでも頭打ちになる(400 点で刻み 6.8 m ≈ 1 画素)
    assert gains[-1] < gains[-3] * 1.05, gains
    # 起伏(最大−最小)は、**1 画素に近い刻みまで細かくすれば**落ち着く。
    # 実測: 100 点以降 350.03 / 354.29 / 354.29 / 354.29(1.2% 以内)。
    fine = reliefs[counts.index(100):]
    assert (max(fine) - min(fine)) / max(fine) < 0.02, reliefs
    # ただし粗すぎる刻みでは山も谷も飛ばすので、起伏も小さく出る
    # (20 点 = 143 m 刻みでは 330.5 m と、7% 低く出た)。
    # 「起伏は刻みに依らない」は無条件には言えない
    assert reliefs[0] < max(fine) * 0.98, reliefs
