"""空間索引が総当たりと同じ答えを返すことの検算(SPEC G-10)。

索引は速さのために二段構え(局所平面の篩 → 上位候補だけ厳密)にしてある。
速くしたぶん、**答えが変わっていないこと**を総当たりで確かめる。
総当たりは索引を一切使わない独立な経路である。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_water import SegmentIndex
from etl.common import point_segment_distance_km

pytestmark = pytest.mark.unit


def brute(lon: float, lat: float, lines: list[tuple[list, str]]):
    """索引を使わずに最小距離と名前を求める。"""
    best, name = float("inf"), None
    for pts, nm in lines:
        for i in range(len(pts) - 1):
            d = point_segment_distance_km(lon, lat, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            if d < best:
                best, name = d, nm
    return (best, name) if name is not None else (None, None)


def make_lines(rng: random.Random, n_lines: int):
    """日本の中くらいの範囲に、折れ線をばらまく。"""
    lines = []
    for i in range(n_lines):
        x = rng.uniform(138.0, 139.0)
        y = rng.uniform(35.5, 36.5)
        pts = [(x, y)]
        for _ in range(rng.randint(1, 8)):
            x += rng.uniform(-0.03, 0.03)
            y += rng.uniform(-0.03, 0.03)
            pts.append((x, y))
        lines.append((pts, f"line-{i}"))
    return lines


def test_索引の答えが総当たりと一致する():
    rng = random.Random(20260908)
    lines = make_lines(rng, 300)
    index = SegmentIndex()
    for pts, nm in lines:
        index.add_line(pts, nm)
    assert len(index) > 500, "線分が少なすぎて検査になっていない"

    worst = 0.0
    checked = 0
    for _ in range(150):
        lon = rng.uniform(138.0, 139.0)
        lat = rng.uniform(35.5, 36.5)
        gi, ni = index.nearest(lon, lat)
        gb, nb = brute(lon, lat, lines)
        assert (gi is None) == (gb is None)
        if gi is None:
            continue
        checked += 1
        # 距離は完全に一致すること(同じ厳密関数を最後に当てているため)
        assert gi == pytest.approx(gb, rel=1e-9), f"({lon},{lat}) 索引 {gi} / 総当たり {gb}"
        worst = max(worst, abs(gi - gb))
    assert checked > 100, f"照合できた点が {checked} 件しかない"


def test_線分が無ければ欠測を返す():
    index = SegmentIndex()
    assert index.nearest(138.0, 36.0) == (None, None)


def test_遠すぎる点は欠測になる():
    """MAX_RINGS の外は探さない。埋めずに欠測を返すこと。"""
    index = SegmentIndex()
    index.add_line([(138.0, 36.0), (138.1, 36.0)], "川")
    d, nm = index.nearest(120.0, 20.0)
    assert d is None and nm is None


def test_名前は最短の線分のものが返る():
    index = SegmentIndex()
    index.add_line([(138.00, 36.00), (138.00, 36.10)], "近い川")
    index.add_line([(138.20, 36.00), (138.20, 36.10)], "遠い川")
    d, nm = index.nearest(138.01, 36.05)
    assert nm == "近い川"
    assert d == pytest.approx(point_segment_distance_km(138.01, 36.05, 138.0, 36.0, 138.0, 36.1), rel=1e-9)
