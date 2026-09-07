"""温泉点と対照点を、地理環境の軸ごとに突き合わせる(SPEC F-10 / 設計書 STEP 1)。

出す数は「温泉のうち何割が○○か」ではなく、**温泉と対照で割合がどれだけ違うか**である。
温泉だけを見た割合は「人が観光地を登録した場所」の性質と区別できない(設計書 §33)。

有意性は置換検定で見る。温泉/対照のラベルだけを入れ替えて χ² を作り直し、
観測した χ² がその分布のどこに来るかを数える。分布の形を仮定しないので、
セル度数が小さい軸でも同じやり方で扱える。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, write_json

SEED = 20260907
PERMUTATIONS = 2000
OUT = DATA / "stats.json"


def band(value, edges: list[float], unit: str) -> str | None:
    if value is None:
        return None
    for i, e in enumerate(edges):
        if value < e:
            return f"〜{e:g} {unit}" if i == 0 else f"{edges[i-1]:g}〜{e:g} {unit}"
    return f"{edges[-1]:g} {unit} 以上"


AXES: list[dict] = [
    {
        "key": "geology_group",
        "label": "地質(大区分)",
        "note": "シームレス地質図V2 の大区分。地点の凡例をそのまま使う",
        "get": lambda p: p.get("geology_group"),
        "order": None,
    },
    {
        "key": "elevation",
        "label": "標高",
        "note": "国土地理院の標高タイル(z14)を読んだ値",
        "get": lambda p: band(p.get("elevation_m"), [200, 500, 800, 1200], "m"),
        "order": ["〜200 m", "200〜500 m", "500〜800 m", "800〜1200 m", "1200 m 以上"],
    },
    {
        "key": "slope",
        "label": "傾斜",
        "note": "標高タイルから Horn 法で求めた傾斜",
        "get": lambda p: band(p.get("slope_deg"), [3, 8, 15, 25], "°"),
        "order": ["〜3 °", "3〜8 °", "8〜15 °", "15〜25 °", "25 ° 以上"],
    },
    {
        "key": "volcano_distance",
        "label": "最寄りの活火山までの距離",
        "note": "気象庁の活火山 111 との球面距離。近いことは火山性であることを意味しない",
        "get": lambda p: band(p.get("distance_to_volcano_km"), [10, 20, 30, 50, 100], "km"),
        "order": ["〜10 km", "10〜20 km", "20〜30 km", "30〜50 km", "50〜100 km", "100 km 以上"],
    },
]


def chi_square(table: list[list[int]]) -> float:
    """2 行 k 列の χ²。期待度数 0 の列は寄与しない。"""
    rows = len(table)
    cols = len(table[0])
    row_sum = [sum(r) for r in table]
    col_sum = [sum(table[i][j] for i in range(rows)) for j in range(cols)]
    total = sum(row_sum)
    if total == 0:
        return 0.0
    stat = 0.0
    for i in range(rows):
        for j in range(cols):
            e = row_sum[i] * col_sum[j] / total
            if e > 0:
                stat += (table[i][j] - e) ** 2 / e
    return stat


def permutation_p(labels: list[int], values: list[str], categories: list[str], observed: float) -> tuple[float, float]:
    """ラベルを入れ替えて χ² の帰無分布を作り、(p 値, 帰無平均) を返す。"""
    rng = random.Random(SEED)
    idx = {c: j for j, c in enumerate(categories)}
    shuffled = labels[:]
    hits = 0
    total = 0.0
    for _ in range(PERMUTATIONS):
        rng.shuffle(shuffled)
        table = [[0] * len(categories), [0] * len(categories)]
        for lab, v in zip(shuffled, values):
            table[lab][idx[v]] += 1
        s = chi_square(table)
        total += s
        if s >= observed:
            hits += 1
    # 片側。0 にしないため (hits + 1) / (N + 1)
    return (hits + 1) / (PERMUTATIONS + 1), total / PERMUTATIONS


def cramers_v(table: list[list[int]], stat: float) -> float:
    n = sum(sum(r) for r in table)
    k = min(len(table), len(table[0]))
    if n == 0 or k < 2:
        return 0.0
    return (stat / (n * (k - 1))) ** 0.5


def main() -> None:
    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    control = json.loads((DATA / "control.geojson").read_text(encoding="utf-8"))

    axes_out = []
    for axis in AXES:
        get = axis["get"]
        a_vals = [v for f in onsen["features"] if (v := get(f["properties"])) is not None]
        b_vals = [v for f in control["features"] if (v := get(f["properties"])) is not None]

        cats = axis["order"]
        if cats is None:
            counts: dict[str, int] = {}
            for v in a_vals + b_vals:
                counts[v] = counts.get(v, 0) + 1
            cats = [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])]
        else:
            present = set(a_vals) | set(b_vals)
            cats = [c for c in cats if c in present]

        table = [[a_vals.count(c) for c in cats], [b_vals.count(c) for c in cats]]
        stat = chi_square(table)
        labels = [0] * len(a_vals) + [1] * len(b_vals)
        p, null_mean = permutation_p(labels, a_vals + b_vals, cats, stat)

        na, nb = sum(table[0]), sum(table[1])
        rows = []
        for j, c in enumerate(cats):
            oa, ob = table[0][j], table[1][j]
            rows.append({
                "category": c,
                "onsen": oa, "control": ob,
                "onsen_pct": round(100 * oa / na, 2) if na else None,
                "control_pct": round(100 * ob / nb, 2) if nb else None,
                "diff_pt": round(100 * oa / na - 100 * ob / nb, 2) if na and nb else None,
            })

        axes_out.append({
            "key": axis["key"], "label": axis["label"], "note": axis["note"],
            "onsen_n": na, "control_n": nb,
            "onsen_missing": len(onsen["features"]) - na,
            "control_missing": len(control["features"]) - nb,
            "rows": rows,
            "chi_square": round(stat, 3),
            "null_mean_chi_square": round(null_mean, 3),
            "p_permutation": round(p, 5),
            "cramers_v": round(cramers_v(table, stat), 4),
        })

    write_json(OUT, {
        "generated_from": {
            "onsen": onsen["metadata"]["counts"]["extracted"],
            "control": control["metadata"]["counts"]["control_total"],
        },
        "method": {
            "control": "同じ P12 観光資源データの温泉以外の点。都道府県ごとに温泉と同数を無作為抽出",
            "test": f"ラベル置換検定 {PERMUTATIONS} 回(seed={SEED})の χ²。p = (観測以上の回数 + 1) / (回数 + 1)",
            "effect_size": "Cramér の V",
            "caution": "これは共起の記述であって、温泉ができる原因を示すものではない",
        },
        "seed": SEED,
        "permutations": PERMUTATIONS,
        "axes": axes_out,
    }, indent=1)

    for a in axes_out:
        print(f"{a['label']}: χ²={a['chi_square']} 帰無平均={a['null_mean_chi_square']} "
              f"p={a['p_permutation']} V={a['cramers_v']} (温泉 {a['onsen_n']} / 対照 {a['control_n']})")


if __name__ == "__main__":
    main()
