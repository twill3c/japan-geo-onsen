"""温泉ごとの AI の説明を作る(設計書 §35)。**ローカルで計算する**(§37)。

## どのモデルで説明するか

loop_013 で合否を判定した Random Forest を、**同じ分割・同じ乱数の種**で学び直す。
各温泉には、**その温泉の都道府県を学習に使っていない分割のモデル**の出力と説明を付ける
(out-of-fold)。学習に使ったモデルで説明すると、Random Forest は点を覚えて 1 に近い値を出し、
説明も「覚えたから」になってしまう。

学び直したモデルが判定したモデルと同じであることは、分割外の出力から計算した ROC-AUC が
baselines.json と一致することで確かめる(tests/test_ai_explain.py)。

## 何を出すか

- `score`: そのモデルの出力(0〜1)。**確率ではない**(Random Forest の出力は較正していない)。
  意味は「P12 に温泉の分類で登録された地点の地理環境にどれだけ似ているか」で、温泉の存在ではない
- `contrib`: SHAP の寄与。前処理後の列(欠測の印・地質の one-hot)に付く値を、元の 8 特徴量へ足し戻す。
  基準値 + 寄与の和 = 出力(加法性)をテストで確かめる
- 出すのは学習に使った P12 の温泉だけ。対照群は地図に出ていない。他の層は母集団が違う
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shap
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.build_ai_dataset import FEATURES, GROUP, ID, LABEL, OUT_CSV
from etl.common import DATA, write_json
from etl.train_baselines import grouped_folds, load_dataset, make_model

MODEL = "random_forest"
OUT = DATA / "ai" / "explanations_onsen.json"


def original_feature(transformed_name: str) -> str:
    """前処理後の列名を元の特徴量へ戻す。

    num__elevation_m → elevation_m / num__missingindicator_elevation_m → elevation_m /
    cat__geology_group_火成岩 → geology_group
    """
    kind, _, rest = transformed_name.partition("__")
    if kind == "cat":
        for f in FEATURES:
            if rest.startswith(f + "_"):
                return f
        raise ValueError(transformed_name)
    if rest.startswith("missingindicator_"):
        rest = rest[len("missingindicator_"):]
    if rest not in FEATURES:
        raise ValueError(transformed_name)
    return rest


def _class1(values, expected):
    """shap の返り値の形の違いを吸収して、正例(クラス 1)の分だけを返す。"""
    if isinstance(values, list):
        return np.asarray(values[1]), float(np.asarray(expected)[1])
    arr = np.asarray(values)
    if arr.ndim == 3:
        return arr[:, :, 1], float(np.asarray(expected)[1])
    return arr, float(np.asarray(expected).ravel()[-1])


def main() -> None:
    X, y, groups = load_dataset()
    ids = pd.read_csv(OUT_CSV, encoding="utf-8")[ID].astype(str).tolist()
    folds = grouped_folds(groups)

    oof = np.full(len(y), np.nan)
    points: dict[str, dict] = {}
    base_by_fold: dict[str, float] = {}
    fold_train_prefs: dict[str, list[str]] = {}
    abs_sum = {f: 0.0 for f in FEATURES}
    n_explained = 0

    for k, (tr, te) in enumerate(folds):
        m = make_model(MODEL)
        m.fit(X.iloc[tr], y[tr])
        proba = m.predict_proba(X.iloc[te])[:, 1]
        oof[te] = proba

        pre, est = m.named_steps["pre"], m.named_steps["model"]
        Xt = pre.transform(X.iloc[te])
        if hasattr(Xt, "toarray"):
            Xt = Xt.toarray()
        names = list(pre.get_feature_names_out())
        groups_of_col = [FEATURES.index(original_feature(n)) for n in names]

        explainer = shap.TreeExplainer(est)
        sv, base = _class1(explainer.shap_values(Xt, check_additivity=True), explainer.expected_value)
        base_by_fold[str(k)] = base
        fold_train_prefs[str(k)] = sorted({groups[i] for i in tr})

        agg = np.zeros((sv.shape[0], len(FEATURES)))
        for col, fi in enumerate(groups_of_col):
            agg[:, fi] += sv[:, col]

        for row_pos, i in enumerate(te):
            if y[i] != 1:
                continue
            contrib = [float(v) for v in agg[row_pos]]
            points[ids[i]] = {
                "score": float(proba[row_pos]),
                "contrib": contrib,
                "fold": k,
                "prefecture": groups[i],
            }
            for fi, f in enumerate(FEATURES):
                abs_sum[f] += abs(contrib[fi])
            n_explained += 1
        print(f"  分割 {k}: 検証 {len(te)} 行 / 基準値 {base:.4f}", flush=True)

    oof_auc = float(roc_auc_score(y, oof))
    write_json(OUT, {
        "model": MODEL,
        "question": "P12 に登録された地点が『温泉』の分類か(温泉の存在ではない)",
        "note": ("score は Random Forest の出力(0〜1)で、確率ではない(較正していない)。"
                 "各温泉には、その都道府県を学習に使っていない分割のモデルの出力と SHAP の寄与を付けた"),
        "features": FEATURES,
        "oof_roc_auc": oof_auc,
        "base_by_fold": base_by_fold,
        "fold_train_prefectures": fold_train_prefs,
        "mean_abs_contrib": {f: abs_sum[f] / n_explained for f in FEATURES},
        "points": points,
    })
    print(f"{OUT}: 温泉 {len(points)} 点 / 分割外 ROC-AUC {oof_auc:.6f}", flush=True)


if __name__ == "__main__":
    main()
