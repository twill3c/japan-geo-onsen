"""ベースラインモデルを比べる(設計書 Phase 5 §53 / §31)。**ローカルで学習する**(§37)。

合否は docs/ai_preregistration.md に学習の前に書いてある。このスクリプトはそのファイルの
SHA-256 を結果に書き込み、テスト(tests/test_ai.py)が一致を確かめる。

- 当てる問い: P12 に登録された地点が温泉の分類か(負例は温泉が無い場所ではない)
- 検証: 都道府県ごとの 5 分割(空間の漏れを避ける)。無作為 5 分割は参考
- モデル: Logistic Regression / Random Forest / XGBoost。
  **ハイパーパラメータは既定に近い値で固定し、結果を見て調整しない**
- 欠測は学習側の分割の中だけで埋める(Pipeline の中に置く)
- 陰性対照: 都道府県の中でラベルを入れ替えて学習し直す
- 説明(§35): 最良モデルの並べ替え重要度(検証側で 1 列ずつ入れ替えたときの ROC-AUC の落ち幅)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_ai_dataset import CATEGORICAL, FEATURES, GROUP, LABEL, NUMERIC, OUT_CSV
from etl.common import REPO, write_json

SEED = 20260915
N_SPLITS = 5
PREREG = REPO / "docs" / "ai_preregistration.md"
OUT = REPO / "public" / "data" / "ai" / "baselines.json"
UNKNOWN = "(不明)"

HYPERPARAMETERS = {
    "logistic": {"max_iter": 2000, "C": 1.0, "standardize": True},
    "random_forest": {"n_estimators": 500, "min_samples_leaf": 2, "random_state": SEED},
    "xgboost": {"n_estimators": 400, "max_depth": 4, "learning_rate": 0.05,
                "subsample": 0.8, "colsample_bytree": 0.8, "random_state": SEED},
}
MODEL_LABELS = {"logistic": "Logistic Regression", "random_forest": "Random Forest", "xgboost": "XGBoost"}


def load_dataset() -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    df = pd.read_csv(OUT_CSV, encoding="utf-8")
    X = df[FEATURES].copy()
    for c in NUMERIC:
        X[c] = pd.to_numeric(X[c], errors="coerce")
    for c in CATEGORICAL:
        X[c] = X[c].fillna(UNKNOWN).astype(str)
    return X, df[LABEL].to_numpy(dtype=int), df[GROUP].astype(str).tolist()


def grouped_folds(groups: list[str]) -> list[tuple[list[int], list[int]]]:
    """都道府県を丸ごと検証側に回す 5 分割(決定的)。"""
    idx = np.arange(len(groups))
    return [(tr.tolist(), te.tolist()) for tr, te in GroupKFold(n_splits=N_SPLITS).split(idx, groups=groups)]


def random_folds(y: np.ndarray) -> list[tuple[list[int], list[int]]]:
    idx = np.arange(len(y))
    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEED)
    return [(tr.tolist(), te.tolist()) for tr, te in skf.split(idx, y)]


def _preprocess(scale: bool, numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    num_steps = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    parts = [("num", Pipeline(num_steps), numeric)]
    if categorical:
        parts.append(("cat", OneHotEncoder(handle_unknown="ignore"), categorical))
    return ColumnTransformer(parts)


def make_model(name: str, numeric: list[str] = NUMERIC, categorical: list[str] = CATEGORICAL) -> Pipeline:
    if name == "logistic":
        h = HYPERPARAMETERS["logistic"]
        est = LogisticRegression(max_iter=h["max_iter"], C=h["C"])
        return Pipeline([("pre", _preprocess(True, numeric, categorical)), ("model", est)])
    if name == "random_forest":
        est = RandomForestClassifier(**HYPERPARAMETERS["random_forest"], n_jobs=2)
        return Pipeline([("pre", _preprocess(False, numeric, categorical)), ("model", est)])
    if name == "xgboost":
        est = XGBClassifier(**HYPERPARAMETERS["xgboost"], n_jobs=2, eval_metric="logloss", tree_method="hist")
        return Pipeline([("pre", _preprocess(False, numeric, categorical)), ("model", est)])
    raise ValueError(name)


def oof_proba(name: str, X: pd.DataFrame, y: np.ndarray, folds, **kw) -> np.ndarray:
    out = np.full(len(y), np.nan)
    for tr, te in folds:
        m = make_model(name, **kw)
        m.fit(X.iloc[tr], y[tr])
        out[te] = m.predict_proba(X.iloc[te])[:, 1]
    assert not np.isnan(out).any(), "検証側に出ない行がある"
    return out


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    pred = (p >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
    }


def evaluate_model(name: str, X: pd.DataFrame, y: np.ndarray, groups: list[str], scheme: str = "grouped") -> dict:
    folds = grouped_folds(groups) if scheme == "grouped" else random_folds(y)
    return metrics(y, oof_proba(name, X, y, folds))


def single_feature_baselines(X: pd.DataFrame, y: np.ndarray, groups: list[str]) -> dict:
    folds = grouped_folds(groups)
    out = {}
    for f in NUMERIC:
        p = oof_proba("logistic", X[[f]], y, folds, numeric=[f], categorical=[])
        out[f] = float(roc_auc_score(y, p))
    return out


def permute_within_groups(y: np.ndarray, groups: list[str], rng: np.random.Generator) -> np.ndarray:
    y2 = y.copy()
    g = np.asarray(groups)
    for name in np.unique(g):
        idx = np.where(g == name)[0]
        y2[idx] = rng.permutation(y[idx])
    return y2


def permutation_importance(name: str, X: pd.DataFrame, y: np.ndarray, groups: list[str],
                           rng: np.random.Generator, repeats: int = 5) -> dict:
    drops = {f: [] for f in FEATURES}
    for tr, te in grouped_folds(groups):
        m = make_model(name)
        m.fit(X.iloc[tr], y[tr])
        Xte = X.iloc[te].reset_index(drop=True)
        base = roc_auc_score(y[te], m.predict_proba(Xte)[:, 1])
        for f in FEATURES:
            for _ in range(repeats):
                Xp = Xte.copy()
                Xp[f] = rng.permutation(Xp[f].to_numpy())
                drops[f].append(base - roc_auc_score(y[te], m.predict_proba(Xp)[:, 1]))
    return {f: {"mean": float(np.mean(v)), "sd": float(np.std(v))} for f, v in drops.items()}


def main() -> None:
    X, y, groups = load_dataset()
    rng = np.random.default_rng(SEED)
    prereg_sha = hashlib.sha256(PREREG.read_bytes()).hexdigest()

    models = {}
    for name in ("logistic", "random_forest", "xgboost"):
        models[name] = {
            "label": MODEL_LABELS[name],
            "grouped": evaluate_model(name, X, y, groups, "grouped"),
            "random": evaluate_model(name, X, y, groups, "random"),
            "hyperparameters": HYPERPARAMETERS[name],
        }
        print(f"{name}: 都道府県分割 AUC {models[name]['grouped']['roc_auc']:.4f} / "
              f"無作為 AUC {models[name]['random']['roc_auc']:.4f}", flush=True)

    best = max(models, key=lambda k: models[k]["grouped"]["roc_auc"])
    singles = single_feature_baselines(X, y, groups)
    best_single = max(singles, key=singles.get)
    print(f"最強の 1 変数: {best_single} AUC {singles[best_single]:.4f}", flush=True)

    y_perm = permute_within_groups(y, groups, rng)
    neg_auc = metrics(y_perm, oof_proba(best, X, y_perm, grouped_folds(groups)))["roc_auc"]
    print(f"陰性対照(都道府県内でラベルを入れ替え): AUC {neg_auc:.4f}", flush=True)

    auc = models[best]["grouped"]["roc_auc"]
    gates = {
        "G-22a": {"rule": "最良モデルの都道府県分割 ROC-AUC ≥ 0.65", "value": auc, "passed": auc >= 0.65},
        "G-22b": {"rule": "最強の 1 変数ベースラインより +0.02 以上", "value": auc - singles[best_single],
                  "passed": (auc - singles[best_single]) >= 0.02},
        "G-22c": {"rule": "陰性対照の ROC-AUC が 0.45〜0.55", "value": neg_auc, "passed": 0.45 <= neg_auc <= 0.55},
    }
    importance = permutation_importance(best, X, y, groups, rng)

    write_json(OUT, {
        "question": "P12 に登録された地点が『温泉』の分類か、温泉以外の観光資源か(負例は温泉が無い場所ではない)",
        "preregistration": "docs/ai_preregistration.md",
        "preregistration_sha256": prereg_sha,
        "seed": SEED,
        "n_splits": N_SPLITS,
        "rows": int(len(y)), "positives": int(y.sum()), "negatives": int(len(y) - y.sum()),
        "prefectures": len(set(groups)),
        "features": FEATURES,
        "versions": {"scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__, "numpy": np.__version__},
        "models": models,
        "best_model": best,
        "baselines": {
            "constant": {"grouped_roc_auc": 0.5},
            "single_feature": singles,
            "best_single_feature": {"feature": best_single, "grouped_roc_auc": singles[best_single]},
        },
        "negative_control": {"method": "都道府県の中でラベルを無作為に入れ替えて同じ手順で学習", "roc_auc": neg_auc},
        "gates": gates,
        "permutation_importance": {"model": best, "metric": "ROC-AUC の落ち幅(都道府県分割の検証側・5 回)",
                                   "features": importance},
    }, indent=1)
    print(json.dumps({k: (v["passed"], round(v["value"], 4)) for k, v in gates.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
