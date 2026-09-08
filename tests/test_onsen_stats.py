"""環境省「温泉利用状況」PDF の読み取りの検算(SPEC G-11)。

この PDF は表を文字として持っているだけで、列の区切りを持っていない。
抽出テキストの行では **47 行のうち 26 行で数字が空白で割れており**、
しかも「4」+「7」(= 47)のように**書式では決められない割れ方**がある。
だから列は文字の座標で切り、「読めた」の判定を**数の性質**に置く。

使う不変量:
  1. 都道府県が 47 行あること(表自身の構造)
  2. 各行の数値が **20 列**であること(見出しの列数)
  3. 利用源泉(自噴+動力) + 未利用源泉(自噴+動力) == 源泉総数
     —— これは表の見出しが「源泉総数 Ａ＋Ｂ」と書いている等式そのもの
  4. 湧出量 自噴 + 動力 == 湧出量 合計
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.parse_onsen_stats import parse_pdf, valid_number

pytestmark = pytest.mark.validation


def test_数の書式の判定():
    """3 桁ごとの区切りとして正しいものだけを通す。"""
    for ok in ("0", "42", "1,089", "13,579,988", "255,608"):
        assert valid_number(ok), ok
    for ng in ("20,79", "1,", "1,83", "2,1", ",100", "1,0000"):
        assert not valid_number(ng), ng


def test_数の書式は切ったあとの検算に使う():
    """位置で切った語が数として読めることを確かめるための判定。

    書式で列を切る方式は捨てた —— 「4」+「7」(= 47)のように
    **両方とも単体で正しい**割れ方があり、書式だけでは決められないため。
    """
    assert valid_number("47") and valid_number("13,579,988")
    assert not valid_number("20,79")


@pytest.fixture(scope="module")
def parsed():
    return parse_pdf()


def test_都道府県が47行ある(parsed):
    assert len(parsed["prefectures"]) == 47
    names = [p["prefecture"] for p in parsed["prefectures"]]
    assert names[0] == "北海道"
    assert names[-1] == "沖縄県"
    assert len(set(names)) == 47


def test_源泉数の内訳と総数の食い違いは富山県の1件だけ(parsed):
    """表の見出しが「源泉総数 Ａ＋Ｂ」と書いている等式。

    出所: 実測 2026-09-08。**47 行のうち 46 行で成り立ち、富山県だけ +1 ずれる**
    (内訳 170 / 総数 169)。列の対応が誤っていれば多くの行で崩れるはずなので、
    これは出典側の不整合と読んだ。直さずそのまま出し、食い違いを記録して画面に書く。

    食い違いが広がったら列の対応を疑うべきなので、件数と大きさを固定して見張る。
    """
    mismatches = []
    for p in parsed["prefectures"]:
        parts = (p["used_self_flowing"] + p["used_pumped"]
                 + p["unused_self_flowing"] + p["unused_pumped"])
        if parts != p["sources_total"]:
            mismatches.append((p["prefecture"], parts - p["sources_total"]))
    assert mismatches == [("富山県", 1)], mismatches
    assert parsed["source_mismatches"] == [{
        "prefecture": "富山県", "sum_of_parts": 170,
        "stated_total": 169, "difference": 1,
    }]


def test_湧出量の内訳が合計と一致する(parsed):
    for p in parsed["prefectures"]:
        assert p["discharge_self_flowing"] + p["discharge_pumped"] == p["discharge_total"], p["prefecture"]


def test_温度別源泉数は総数と一致しない(parsed):
    """**一致しない**ことを検査する。

    温度別の 4 区分を足しても源泉総数には届かない(温度が測られていない源泉がある)。
    これは読み取りの誤りではなく表の性質なので、そう書いておかないと
    後から「解析が壊れている」と誤読される。全国の欠測率も一緒に測る。
    """
    total = sum(p["sources_total"] for p in parsed["prefectures"])
    by_temp = sum(p["temp_under25"] + p["temp_25_42"] + p["temp_over42"] + p["temp_steam_gas"]
                  for p in parsed["prefectures"])
    assert by_temp < total, "温度別が総数と一致するなら、この検査と説明文を作り直す"
    assert parsed["temperature_coverage"] == pytest.approx(by_temp / total, rel=1e-9)
    # 桁の確認(実測 2026-09-08 で 0.7 台)。大きく動いたら読み直す
    assert 0.6 < parsed["temperature_coverage"] < 0.95


def test_全国合計が公表の桁に収まる(parsed):
    """出所: 環境省「令和6年度温泉利用状況」(令和7年3月末現在)。

    源泉総数はおよそ 2 万7千、宿泊施設はおよそ 1 万2千という桁である。
    桁が変わったら PDF の版か読み取りを疑う。
    """
    total = sum(p["sources_total"] for p in parsed["prefectures"])
    lodging = sum(p["lodging_facilities"] for p in parsed["prefectures"])
    assert 20000 < total < 40000, total
    assert 8000 < lodging < 20000, lodging


def test_負の値や欠測が無い(parsed):
    for p in parsed["prefectures"]:
        for k, v in p.items():
            if isinstance(v, int):
                assert v >= 0, f"{p['prefecture']} {k} = {v}"
