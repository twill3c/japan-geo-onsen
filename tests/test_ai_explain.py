"""温泉ごとの AI の説明の検算(SPEC G-23 / 設計書 §35)。

- 説明に使うモデルは、**その温泉の都道府県を学習に使っていない**(out-of-fold)
- SHAP の加法性: 基準値 + 8 特徴量の寄与の和 = そのモデルの出力(前処理後の列を元の特徴量へ足し戻しても崩れない)
- 分割外の出力から計算した ROC-AUC が、loop_013 の結果(baselines.json の Random Forest)と一致する
  —— 説明のために学習し直したモデルが、合否を判定したモデルと同じであることの照合
- 学習に使った P12 の温泉すべてに説明があり、それ以外(対照群・他の層)は出していない
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_ai_dataset import FEATURES, load_rows
from etl.common import DATA, REPO

pytestmark = pytest.mark.validation

EXPLAIN = DATA / "ai" / "explanations_onsen.json"
BASELINES = REPO / "public" / "data" / "ai" / "baselines.json"


@pytest.fixture(scope="module")
def doc():
    return json.loads(EXPLAIN.read_text(encoding="utf-8"))


def test_説明の特徴量が学習の特徴量と同じ並び(doc):
    assert doc["features"] == FEATURES


def test_学習に使った温泉すべてに説明があり他は出していない(doc):
    rows = load_rows()
    onsen_ids = {r["point_id"] for r in rows if r["label"] == 1}
    assert set(doc["points"]) == onsen_ids


def test_説明に使ったモデルはその都道府県を学習していない(doc):
    """out-of-fold であることの確認。学習に使ったモデルの説明は、点を覚えた値になる。"""
    train_prefs = {int(k): set(v) for k, v in doc["fold_train_prefectures"].items()}
    for pid, p in doc["points"].items():
        assert p["prefecture"] not in train_prefs[p["fold"]], (pid, p["prefecture"], p["fold"])


def test_SHAP_の加法性(doc):
    """基準値 + 寄与の和 = 出力。元の特徴量へ足し戻しても崩れないこと。"""
    worst = 0.0
    for pid, p in doc["points"].items():
        assert len(p["contrib"]) == len(FEATURES)
        total = doc["base_by_fold"][str(p["fold"])] + sum(p["contrib"])
        worst = max(worst, abs(total - p["score"]))
    assert worst < 1e-6, worst


def test_分割外の出力が合否を判定したモデルと一致する(doc):
    base = json.loads(BASELINES.read_text(encoding="utf-8"))
    assert doc["model"] == base["best_model"] == "random_forest"
    assert doc["oof_roc_auc"] == pytest.approx(base["models"]["random_forest"]["grouped"]["roc_auc"], abs=1e-12)


def test_出力は0から1で確率とは呼ばない(doc):
    for p in doc["points"].values():
        assert 0.0 <= p["score"] <= 1.0
    assert "確率ではない" in doc["note"]


def test_全体の寄与の大きさの順が記録されている(doc):
    imp = doc["mean_abs_contrib"]
    assert set(imp) == set(FEATURES)
    assert all(v >= 0 for v in imp.values())
