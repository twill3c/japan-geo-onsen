"""AI のデータセットとベースライン比較の検算(SPEC G-22 / docs/ai_preregistration.md)。

- データセットに漏れの列が入っていない(ラベルそのもの・ラベルの作り方を映す列)
- 都道府県の分割で、同じ都道府県が学習と検証の両方に入らない
- 結果の JSON が事前登録ファイルの SHA-256 を持ち、合否の判定が数字と一致する
- 決定的に再現できるモデル(ロジスティック回帰)は、テストの中で学習し直して数字が一致する
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_ai_dataset import FEATURES, GROUP, LABEL, LEAKY, OUT_CSV, load_rows
from etl.common import REPO

pytestmark = pytest.mark.validation

PREREG = REPO / "docs" / "ai_preregistration.md"
RESULTS = REPO / "public" / "data" / "ai" / "baselines.json"


@pytest.fixture(scope="module")
def results():
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_正例と負例が同数で都道府県ごとにも揃う():
    rows = load_rows()
    pos = [r for r in rows if r[LABEL] == 1]
    neg = [r for r in rows if r[LABEL] == 0]
    assert len(pos) == len(neg) == 1320
    from collections import Counter
    assert Counter(r[GROUP] for r in pos) == Counter(r[GROUP] for r in neg), "対照群は都道府県ごとに同数のはず"


def test_特徴量に漏れの列が無い():
    assert not (set(FEATURES) & LEAKY)
    with OUT_CSV.open(encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert not (set(header) & (LEAKY - {GROUP})), "漏れの列が CSV に出ている"


def test_植生自然度の98と99は数として使わない():
    rows = load_rows()
    vals = {r["vegetation_naturalness"] for r in rows if r["vegetation_naturalness"] is not None}
    assert vals and max(vals) <= 10 and min(vals) >= 1


def test_都道府県の分割が都道府県をまたがない():
    from etl.train_baselines import grouped_folds

    rows = load_rows()
    groups = [r[GROUP] for r in rows]
    folds = list(grouped_folds(groups))
    assert len(folds) == 5
    for train, test in folds:
        assert not ({groups[i] for i in train} & {groups[i] for i in test})
    covered = sorted(i for _, test in folds for i in test)
    assert covered == list(range(len(rows))), "検証側に全行がちょうど 1 回ずつ出ること"


def test_結果が事前登録ファイルに結び付いている(results):
    digest = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    assert results["preregistration_sha256"] == digest, "事前登録ファイルが結果を出した後に書き換えられている"


def test_合否の判定が数字と一致する(results):
    g = results["gates"]
    best = results["best_model"]
    auc = results["models"][best]["grouped"]["roc_auc"]
    base = results["baselines"]["best_single_feature"]["grouped_roc_auc"]
    neg = results["negative_control"]["roc_auc"]
    assert all(results["models"][best]["grouped"]["roc_auc"] >= results["models"][m]["grouped"]["roc_auc"]
               for m in results["models"])
    assert g["G-22a"]["passed"] == (auc >= 0.65)
    assert g["G-22b"]["passed"] == (auc - base >= 0.02)
    assert g["G-22c"]["passed"] == (0.45 <= neg <= 0.55)


def test_ロジスティック回帰は学習し直して数字が一致する(results):
    """決定的なモデルだけ、テストの中で学習し直す(乱数に依らない照合)。"""
    from etl.train_baselines import evaluate_model, load_dataset

    X, y, groups = load_dataset()
    got = evaluate_model("logistic", X, y, groups, scheme="grouped")
    want = results["models"]["logistic"]["grouped"]
    for k in ("roc_auc", "pr_auc", "accuracy", "f1"):
        assert got[k] == pytest.approx(want[k], abs=1e-9), k


def test_設計書の指標がすべて出ている(results):
    for m in ("logistic", "random_forest", "xgboost"):
        for scheme in ("grouped", "random"):
            keys = set(results["models"][m][scheme])
            assert {"accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"} <= keys, (m, scheme)
