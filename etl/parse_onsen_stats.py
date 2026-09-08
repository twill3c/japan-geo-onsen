"""環境省「令和6年度温泉利用状況」PDF を都道府県別の表にする。

この PDF は**温泉の泉温と湧出量について、日本で唯一まとまって公開されている実データ**である。
地点別のものは存在しないので(SPEC §6)、本アプリで泉温を語れる唯一の足場になる。

読み取りの難所と、それを捨てた経緯(2026-09-08)。

**pypdf の行テキストからは読めない。** 抽出された 1 行の中で数字が空白で割れており、
割れ方が 3 種類あった。

  「20,79」+「1」    区切りの手前で切れる
  「4,296」+「,081」 区切りの直後で切れる
  「4」+「7」        両方とも単体では正しい数(= 47)

3 種類目は**書式だけでは決められない**。「4」と「7」が 2 列なのか 1 つの数なのかは、
文字の並びからは判定できない。書式で繋ぐやり方はここで破綻した。

**代わりに文字の位置で切る。** pdfplumber の `extract_words` は文字の座標から語を作るので、
数の中の細い隙間と列の間の広い隙間を取り違えない。実測すると
**全 47 行が例外なく 20 語**になった。推測の要らない経路なのでこちらを採る。

出典: 環境省「温泉に関するデータ」令和6年度温泉利用状況(令和7年3月末現在)
      https://www.env.go.jp/nature/onsen/data/
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, RAW, write_json

PDF = RAW / "env" / "R6_onsen_riyou.pdf"
OUT = DATA / "onsen_stats.json"

N_COLUMNS = 20

# 表の見出し(縦書きで積まれている)を読み解いた列の並び。
# 源泉数: 総数(Ａ＋Ｂ) / 利用源泉Ａ(自噴・動力) / 未利用源泉Ｂ(自噴・動力) / 温度別 4 区分
# 湧出量: 合計・自噴・動力
COLUMNS = [
    "health_centers",          # 管轄保健所数
    "municipalities",          # 市町村数
    "onsen_areas",             # 温泉地数
    "sources_total",           # 源泉総数(Ａ＋Ｂ)
    "used_self_flowing",       # 利用源泉Ａ 自噴
    "used_pumped",             # 利用源泉Ａ 動力
    "unused_self_flowing",     # 未利用源泉Ｂ 自噴
    "unused_pumped",           # 未利用源泉Ｂ 動力
    "temp_under25",            # 温度別 25度未満
    "temp_25_42",              # 温度別 25度以上42度未満
    "temp_over42",             # 温度別 42度以上
    "temp_steam_gas",          # 温度別 水蒸気・ガス
    "discharge_total",         # 湧出量 合計(L/分)
    "discharge_self_flowing",  # 湧出量 自噴
    "discharge_pumped",        # 湧出量 動力
    "lodging_facilities",      # 宿泊施設数
    "capacity",                # 収容定員
    "lodging_nights",          # 年度延宿泊利用人員
    "public_baths",            # 温泉利用の公衆浴場数
    "hoyo_lodging_nights",     # 国民保養温泉地 年度延宿泊利用人員
]
assert len(COLUMNS) == N_COLUMNS

PREF_NAME = re.compile(r"^(北海道|東京都|京都府|大阪府|.{2,3}県)$")
# 3 桁区切りとして正しい形。区切りの無い数も許す。
# 位置で切ったあとの**検算**に使う(切るためには使わない)
VALID = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)$")


def valid_number(token: str) -> bool:
    """「1,089」は通し「20,79」「1,」は通さない。"""
    return bool(VALID.match(token))


def to_int(token: str) -> int:
    return int(token.replace(",", ""))


def parse_pdf(path: Path | None = None) -> dict:
    import collections

    import pdfplumber

    src = path or PDF
    if not src.exists():
        raise SystemExit(
            f"{src} が無い。次で取得すること:\n"
            "  curl -L -o raw/env/R6_onsen_riyou.pdf https://www.env.go.jp/nature/onsen/pdf/6-7_p_1.pdf"
        )
    with pdfplumber.open(str(src)) as pdf:
        words = [w for page in pdf.pages for w in page.extract_words()]

    # 同じ高さにある語を 1 行にまとめる
    by_row: dict[float, list[dict]] = collections.defaultdict(list)
    for w in words:
        by_row[round(w["top"], 1)].append(w)

    rows = []
    for top in sorted(by_row):
        line = sorted(by_row[top], key=lambda w: w["x0"])
        if not PREF_NAME.match(line[0]["text"]):
            continue
        name = line[0]["text"]
        tokens = [w["text"] for w in line[1:]]
        if len(tokens) != N_COLUMNS:
            raise SystemExit(
                f"{name}: {len(tokens)} 語しか取れなかった({N_COLUMNS} 列のはず): {tokens}"
            )
        for t in tokens:
            if not valid_number(t):
                raise SystemExit(f"{name}: 数として読めない語がある: {t!r}")
        rec = {"prefecture": name}
        rec.update(dict(zip(COLUMNS, (to_int(t) for t in tokens))))
        rows.append(rec)

    if len(rows) != 47:
        raise SystemExit(f"都道府県の行が {len(rows)} 行しか取れなかった(47 行のはず)")

    # 表の見出しが宣言している等式。ここが大きく崩れたら列の対応が間違っている。
    #
    # 実測(2026-09-08): 47 行のうち **46 行で成り立ち、富山県だけ +1 ずれる**
    # (内訳 170 / 総数 169)。列の対応が誤っていれば多くの行で崩れるはずなので、
    # これは出典側の不整合と判断した。**黙って直さず、そのまま出して記録する。**
    # ただし崩れが広がったら列の対応を疑うべきなので、そこで止める。
    MAX_MISMATCH_ROWS = 2
    MAX_MISMATCH_SIZE = 5
    source_mismatches = []
    for r in rows:
        parts = (r["used_self_flowing"] + r["used_pumped"]
                 + r["unused_self_flowing"] + r["unused_pumped"])
        if parts != r["sources_total"]:
            source_mismatches.append({
                "prefecture": r["prefecture"],
                "sum_of_parts": parts,
                "stated_total": r["sources_total"],
                "difference": parts - r["sources_total"],
            })
        if r["discharge_self_flowing"] + r["discharge_pumped"] != r["discharge_total"]:
            raise SystemExit(f"{r['prefecture']}: 湧出量の内訳が合計と合わない")

    if len(source_mismatches) > MAX_MISMATCH_ROWS or any(
        abs(m["difference"]) > MAX_MISMATCH_SIZE for m in source_mismatches
    ):
        raise SystemExit(
            "源泉数の内訳と総数の食い違いが広い。列の対応を疑うこと: "
            + repr(source_mismatches)
        )

    total_sources = sum(r["sources_total"] for r in rows)
    by_temp = sum(r["temp_under25"] + r["temp_25_42"] + r["temp_over42"] + r["temp_steam_gas"]
                  for r in rows)

    return {
        "source": "環境省",
        "dataset": "令和6年度温泉利用状況(令和7年3月末現在)",
        "source_url": "https://www.env.go.jp/nature/onsen/data/",
        "license": "環境省ホームページ利用規約(出典明示)",
        "license_url": "https://www.env.go.jp/help.html",
        "download_date": "2026-09-07",
        "processing_method": (
            f"PDF から文字の座標つきで語を取り出し(pdfplumber)、同じ高さの語を 1 行にまとめて "
            f"都道府県 47 行・各 {N_COLUMNS} 列に分けた。"
            "抽出テキストの行では数字が空白で割れており書式だけでは列を決められないため、"
            "文字の位置で切っている。"
            "源泉数の内訳が総数と一致すること、湧出量の内訳が合計と一致することを全 47 行で検算している"
        ),
        "columns": COLUMNS,
        # 出典側の不整合。直さずそのまま出し、画面にも書く
        "source_mismatches": source_mismatches,
        "national": {
            "sources_total": total_sources,
            "sources_with_temperature": by_temp,
            "discharge_total_l_per_min": sum(r["discharge_total"] for r in rows),
            "lodging_facilities": sum(r["lodging_facilities"] for r in rows),
            "onsen_areas": sum(r["onsen_areas"] for r in rows),
            "temp_under25": sum(r["temp_under25"] for r in rows),
            "temp_25_42": sum(r["temp_25_42"] for r in rows),
            "temp_over42": sum(r["temp_over42"] for r in rows),
            "temp_steam_gas": sum(r["temp_steam_gas"] for r in rows),
        },
        # 温度別の 4 区分は総数に届かない(温度が測られていない源泉がある)
        "temperature_coverage": by_temp / total_sources,
        "prefectures": rows,
    }


def add_coverage(doc: dict) -> dict:
    """手元の温泉点(P12)が、環境省の数に対してどれだけを写しているかを付ける。

    この対比が、地図の点を「日本の温泉の一覧」と読まれないための歯止めになる。
    """
    import json

    onsen = json.loads((DATA / "onsen.geojson").read_text(encoding="utf-8"))
    by_pref: dict[str, int] = {}
    for f in onsen["features"]:
        name = f["properties"].get("prefecture")
        if name:
            by_pref[name] = by_pref.get(name, 0) + 1

    rows = []
    for r in doc["prefectures"]:
        rows.append({
            "prefecture": r["prefecture"],
            "points": by_pref.get(r["prefecture"], 0),
            "onsen_areas": r["onsen_areas"],
            "sources_total": r["sources_total"],
        })
    total_points = sum(x["points"] for x in rows)
    doc["coverage"] = {
        "note": ("地図の点は国土数値情報の観光資源データから採ったもので、"
                 "環境省が数えている温泉地・源泉の一覧ではない。両者の数を並べて置く"),
        "points_total": total_points,
        "onsen_areas_total": doc["national"]["onsen_areas"],
        "sources_total": doc["national"]["sources_total"],
        "points_per_onsen_area": total_points / doc["national"]["onsen_areas"],
        "prefectures_with_zero_points": [x["prefecture"] for x in rows if x["points"] == 0],
        "rows": rows,
    }
    return doc


if __name__ == "__main__":
    doc = add_coverage(parse_pdf())
    write_json(OUT, doc, indent=1)
    c = doc["coverage"]
    print(f"  地図の点 {c['points_total']:,} 対 温泉地 {c['onsen_areas_total']:,}"
          f"({100*c['points_per_onsen_area']:.0f}%)・源泉 {c['sources_total']:,}")
    print(f"  点が 0 の都道府県 {len(c['prefectures_with_zero_points'])}: "
          f"{'・'.join(c['prefectures_with_zero_points'])}")
    n = doc["national"]
    print(f"{OUT}: 47 都道府県")
    print(f"  源泉総数 {n['sources_total']:,} / うち温度の記録がある {n['sources_with_temperature']:,} "
          f"({100*doc['temperature_coverage']:.1f}%)")
    print(f"  湧出量 合計 {n['discharge_total_l_per_min']:,} L/分")
    print(f"  温度別: 25度未満 {n['temp_under25']:,} / 25〜42度 {n['temp_25_42']:,} / "
          f"42度以上 {n['temp_over42']:,} / 水蒸気ガス {n['temp_steam_gas']:,}")
    print(f"  宿泊施設 {n['lodging_facilities']:,} / 温泉地 {n['onsen_areas']:,}")
