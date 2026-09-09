"""凡例の色が色覚型を変えても見分けられるかを測る(SPEC G-17 / HC-257)。

地図の点は**色でしか層を見分けられない**。形は同じ丸で、大きさも近い。
だから色が潰れれば、層を分けたこと自体が意味を失う。この故障は溢れ・重なり・
切れの検査では捕まらず、正常視の作者の目でも見つからない。

色の値は **実ファイルから読み出す**(定数を二重に書かない)。lib/layers.ts の
レイヤー色、components/MapView.tsx の火山の色、globals.css の地図の下地。

計器(色覚シミュレータ)は、壊れていても「それらしい色」を返す。だから
**先に錨で検算してから**本題を測る。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.color import VISION_TYPES, anchors_ok, distance, min_distance
from etl.common import REPO

pytestmark = pytest.mark.unit

# 見分けられなければならない最小の色差。10 は「隣り合わせに置いても違う色に見える」目安。
MIN_DELTA_E = 10.0


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def palette() -> dict[str, str]:
    """画面に実際に出ている色を、ソースから読み出して集める。"""
    layers = _read("lib/layers.ts")
    colors = {}
    for m in re.finditer(r"id:\s*'(onsen[a-z-]*)',[\s\S]{0,400}?color:\s*'(#[0-9a-fA-F]{6})'", layers):
        colors[m.group(1)] = m.group(2)
    assert len(colors) >= 3, f"点レイヤーの色を読み出せていない: {colors}"

    mapview = _read("components/MapView.tsx")
    m = re.search(
        r"'circle-color':\s*\['case',\s*\['get',\s*'warning_level_operated'\],\s*"
        r"'(#[0-9a-fA-F]{6})',\s*'(#[0-9a-fA-F]{6})'\]",
        mapview,
    )
    assert m, "火山の色を読み出せていない"
    colors["volcano-warning"] = m.group(1)
    colors["volcano"] = m.group(2)

    css = _read("app/globals.css")
    bg = re.search(r"background-color':\s*'(#[0-9a-fA-F]{6})'", mapview) or \
        re.search(r"--bg:\s*(#[0-9a-fA-F]{6})", css)
    assert bg, "地図の下地の色を読み出せていない"
    colors["basemap-bg"] = bg.group(1)
    return colors


def test_計器が錨を通る():
    """無彩色は動かず、赤と緑は 2 型で縮む。

    これを確かめずに数値を読むと、壊れた計器で偽の欠陥を作る(実際に一度作りかけた)。
    """
    assert anchors_ok() == []


def test_計器が壊れていれば錨で気づける():
    """陽性対照。恒等変換(何もしないシミュレータ)は錨を通ってはならない。"""
    import etl.color as color

    original = color.simulate
    try:
        color.simulate = lambda rgb, kind: tuple(rgb)   # 何も変えない偽の計器
        assert color.anchors_ok(), "恒等変換が錨を通ってしまう。この検算は空振りしている"
    finally:
        color.simulate = original


def test_点レイヤーの色が三視型すべてで見分けられる(palette):
    d, a, b, kind = min_distance(palette)
    assert d >= MIN_DELTA_E, (
        f"{a} と {b} が {kind} で ΔE00 {d:.1f} しかない(必要 {MIN_DELTA_E})。"
        f"色: {palette[a]} / {palette[b]}"
    )


@pytest.mark.parametrize("kind", VISION_TYPES)
def test_温泉と火山が別の色に見える(kind, palette):
    """かつて ΔE00 0.1(2 型)だった組。ここが本件の再発防止。"""
    d = distance(palette["onsen"], palette["volcano"], kind)
    assert d >= MIN_DELTA_E, f"温泉と火山が {kind} で ΔE00 {d:.1f}"


def test_下地の上でどの点も見える(palette):
    for name, hexv in palette.items():
        if name == "basemap-bg":
            continue
        for kind in VISION_TYPES:
            d = distance(hexv, palette["basemap-bg"], kind)
            assert d >= MIN_DELTA_E, f"{name} が下地と {kind} で ΔE00 {d:.1f}"
