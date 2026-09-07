"""点と折れ線の距離の検算(SPEC G-09)。

温泉から最寄りの河川・湖沼までの距離は「点と線分の距離」の最小値である。
球面上でこれを厳密に解くのは重いので、地点まわりで局所平面に落として解く。
その近似が許されるかどうかを、**線分を細かく刻んで大円距離の最小を取る**
という独立な方法(オラクル)と突き合わせて確かめる。

オラクルは実装と別経路である: 刻み方式は線分の内点を明示的に列挙するだけで、
局所平面への投影を一切使わない。
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import haversine_km, point_polyline_distance_km, point_segment_distance_km

pytestmark = pytest.mark.unit


def densified_min_km(plon: float, plat: float, alon: float, alat: float,
                     blon: float, blat: float, n: int = 20000) -> float:
    """線分を n 等分して大円距離の最小を取る(オラクル)。"""
    best = float("inf")
    for i in range(n + 1):
        t = i / n
        best = min(best, haversine_km(plon, plat, alon + (blon - alon) * t, alat + (blat - alat) * t))
    return best


def test_線分上の点は距離ゼロ():
    d = point_segment_distance_km(138.5, 36.0, 138.0, 36.0, 139.0, 36.0)
    assert d == pytest.approx(0.0, abs=1e-6)


def test_端点の外側では端点までの距離になる():
    """線分の延長上に外れた点は、最寄りの端点までの大円距離と一致するはず。"""
    plon, plat = 137.0, 36.0
    d = point_segment_distance_km(plon, plat, 138.0, 36.0, 139.0, 36.0)
    assert d == pytest.approx(haversine_km(plon, plat, 138.0, 36.0), rel=2e-3)


def test_緯線に垂直な距離が解析解と一致する():
    """北緯 36 度の緯線に対し、0.1 度北の点からの距離。

    出所: 子午線方向の 1 度は約 111.32 km(WGS84 の平均)。ここでは
    オラクル(刻み方式)を正とし、解析値は桁の確認にだけ使う。
    """
    d = point_segment_distance_km(138.5, 36.1, 138.0, 36.0, 139.0, 36.0)
    oracle = densified_min_km(138.5, 36.1, 138.0, 36.0, 139.0, 36.0)
    assert d == pytest.approx(oracle, rel=1e-3)
    assert 11.0 < d < 11.2, f"0.1 度はおよそ 11.1 km のはずが {d}"


def test_退化した線分は点との距離になる():
    d = point_segment_distance_km(138.5, 36.0, 138.0, 36.0, 138.0, 36.0)
    assert d == pytest.approx(haversine_km(138.5, 36.0, 138.0, 36.0), rel=1e-6)


def test_無作為の配置でオラクルと一致する():
    """日本の範囲で無作為に点と線分を作り、刻み方式と 0.5% 以内で一致すること。"""
    rng = random.Random(20260908)
    worst = 0.0
    for _ in range(120):
        plon = rng.uniform(129.0, 145.0)
        plat = rng.uniform(31.0, 45.0)
        # 線分は 1〜60 km 程度の長さにする(河川の 1 区間の想定)
        alon = plon + rng.uniform(-0.5, 0.5)
        alat = plat + rng.uniform(-0.5, 0.5)
        blon = alon + rng.uniform(-0.4, 0.4)
        blat = alat + rng.uniform(-0.4, 0.4)
        got = point_segment_distance_km(plon, plat, alon, alat, blon, blat)
        want = densified_min_km(plon, plat, alon, alat, blon, blat, n=4000)
        if want > 0.01:
            worst = max(worst, abs(got - want) / want)
    assert worst < 0.005, f"最大相対差 {worst:.5f}"


def test_折れ線では全区間の最小が返る():
    line = [(138.0, 36.0), (139.0, 36.0), (139.0, 37.0)]
    p = (139.0, 36.5)
    d = point_polyline_distance_km(p[0], p[1], line)
    # 3 点目までの区間上に載っているので 0
    assert d == pytest.approx(0.0, abs=1e-6)
    # 区間ごとに解いた最小と一致すること
    each = [point_segment_distance_km(p[0], p[1], *line[i], *line[i + 1]) for i in range(len(line) - 1)]
    assert d == pytest.approx(min(each), abs=1e-9)


def test_空の折れ線は距離を返さない():
    assert point_polyline_distance_km(138.0, 36.0, []) is None
    assert point_polyline_distance_km(138.0, 36.0, [(138.0, 36.0)]) == pytest.approx(0.0, abs=1e-9)


def _max_deviation(orig, simplified) -> float:
    """間引いた折れ線が、元の各頂点からどれだけ離れたかの最大値(度)。"""
    worst = 0.0
    for px, py in orig:
        best = min(
            _pt_seg(px, py, simplified[i][0], simplified[i][1],
                    simplified[i + 1][0], simplified[i + 1][1])
            for i in range(len(simplified) - 1)
        )
        worst = max(worst, best)
    return worst


def _pt_seg(px, py, ax, ay, bx, by) -> float:
    import math
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    if den == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / den
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def test_間引きは端点を動かさない():
    from etl.build_water import simplify
    pts = [(138.0 + i * 0.001, 36.0 + 0.0002 * (i % 3)) for i in range(50)]
    s = simplify(pts, 0.0005)
    assert s[0] == pts[0]
    assert s[-1] == pts[-1]
    assert len(s) <= len(pts)


def test_間引きの誤差が許容値を超えない():
    """Douglas-Peucker の定義そのもの。配る線が元からどれだけずれるかを測る。"""
    import random
    rng = random.Random(20260908)
    from etl.build_water import simplify
    for tol in (0.0002, 0.0005, 0.002):
        x, y = 138.0, 36.0
        pts = [(x, y)]
        for _ in range(400):
            x += rng.uniform(-0.002, 0.002)
            y += rng.uniform(-0.002, 0.002)
            pts.append((x, y))
        s = simplify(pts, tol)
        assert len(s) >= 2
        assert _max_deviation(pts, s) <= tol + 1e-12, f"tol={tol} で許容を超えた"


def test_間引きは頂点を減らす():
    """ほぼ直線なら大きく減ること(対照が空振りしていないことの確認)。"""
    from etl.build_water import simplify
    straight = [(138.0 + i * 0.001, 36.0) for i in range(200)]
    assert len(simplify(straight, 0.0005)) == 2
