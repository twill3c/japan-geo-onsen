"""標準地域メッシュ(3 次メッシュ)の座標変換の検算(SPEC G-13)。

植生データはメッシュコードでしか位置を持たないので、コードを緯度経度に
直せなければ地図にも載せられないし、温泉点との突き合わせもできない。

3 次メッシュ(約 1 km)のコードは 8 桁で、次のように組み立てられている。

    1〜2 桁  緯度 × 1.5 の整数部        (1 次メッシュの南端 = この値 / 1.5 度)
    3〜4 桁  経度 − 100 の整数部        (1 次メッシュの西端 = 100 + この値 度)
    5 桁     1 次を南北 8 等分した番号   (0〜7)
    6 桁     1 次を東西 8 等分した番号   (0〜7)
    7 桁     2 次を南北 10 等分した番号  (0〜9)
    8 桁     2 次を東西 10 等分した番号  (0〜9)

したがって 3 次メッシュ 1 個の大きさは 緯度 30 秒 × 経度 45 秒 である。

検算は「往復」と「外部権威」の二本立てにする。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.mesh import MESH3_DLAT, MESH3_DLON, mesh3_bounds, mesh3_center, point_to_mesh3

pytestmark = pytest.mark.unit


def test_メッシュ一個の大きさ():
    """3 次メッシュは緯度 30 秒 × 経度 45 秒。"""
    assert MESH3_DLAT == pytest.approx(30 / 3600, rel=1e-12)
    assert MESH3_DLON == pytest.approx(45 / 3600, rel=1e-12)


def test_1次メッシュの南西端():
    """出所: 標準地域メッシュの定義。

    コード 5339 は「緯度 53/1.5 = 35.3333…度、経度 100+39 = 139 度」の南西端を持つ。
    3 次メッシュ 533900 00 はその 1 次メッシュの南西隅にあたる。
    """
    w, s, e, n = mesh3_bounds("53390000")
    assert s == pytest.approx(53 / 1.5, rel=1e-12)
    assert w == pytest.approx(139.0, rel=1e-12)
    assert n == pytest.approx(s + MESH3_DLAT, rel=1e-12)
    assert e == pytest.approx(w + MESH3_DLON, rel=1e-12)


def test_東京都心のメッシュ():
    """出所: 標準地域メッシュの通説。東京駅(35.681, 139.767)は 3 次メッシュ 53394611。

    外部権威として広く使われている対応。ここが合えば桁の組み立ては正しい。
    """
    assert point_to_mesh3(139.767, 35.681) == "53394611"


def test_往復して同じコードに戻る():
    """コード → 中心 → コード が恒等になること。

    実データの全 368,727 メッシュではなく、桁の組み合わせを網羅する合成コードで見る。
    """
    # 5〜6 桁目は 1 次を 8 等分する番号なので 0〜7、7〜8 桁目は 10 等分なので 0〜9。
    # ここを取り違えて 9 を混ぜると、実装が正しくても落ちる(実際に一度落とした)
    for lat2 in ("30", "36", "45", "68"):
        for lon2 in ("22", "39", "45", "52"):
            for a in "0257":
                for b in "0367":
                    for c in "0459":
                        for d in "0189":
                            code = f"{lat2}{lon2}{a}{b}{c}{d}"
                            lon, lat = mesh3_center(code)
                            assert point_to_mesh3(lon, lat) == code, code


def test_隣り合うメッシュが接している():
    """東へ 1 つ、北へ 1 つ動かすと、境界がぴたりと合うこと。"""
    w, s, e, n = mesh3_bounds("53394611")
    east = mesh3_bounds(point_to_mesh3(e + MESH3_DLON / 2, s + MESH3_DLAT / 2))
    north = mesh3_bounds(point_to_mesh3(w + MESH3_DLON / 2, n + MESH3_DLAT / 2))
    assert east[0] == pytest.approx(e, rel=1e-12)
    assert north[1] == pytest.approx(n, rel=1e-12)


def test_桁が足りないコードは例外():
    """黙って通る道を作らない(HC-075)。"""
    for bad in ("5339461", "533946110", "", "abcdefgh"):
        with pytest.raises(ValueError):
            mesh3_bounds(bad)


def test_区画の番号が範囲外なら例外():
    """5〜6 桁目は 0〜7、7〜8 桁目は 0〜9 でなければならない。"""
    with pytest.raises(ValueError):
        mesh3_bounds("53398611")   # 5 桁目が 8
    with pytest.raises(ValueError):
        mesh3_bounds("53394811")   # 6 桁目が 8
