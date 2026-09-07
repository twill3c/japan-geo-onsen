"""国土数値情報 P12 観光資源(2014)から温泉点の素の GeoJSON を作る。

採録規則(実測 2026-09-07):
  P12 は「観光資源台帳(A級以上)」と「観光地点等名簿」を統合したデータで、
  前者は 種別名称(P12_005) を持ち、後者は 観光資源分類コード(P12_007) を持つ。
  したがって温泉は次の二つの経路で現れる。

    経路 A: 種別名称 == "温泉"                     … 全国 33 点
    経路 B: 観光資源分類コード == "3"(温泉・健康)   … 全国 1,297 点

  分類コード 3 は「温泉・健康」であり温泉そのものではない。名称に「温泉」「湯」を
  含むかどうかは属性として持たせ、フィルタは利用者に委ねる(勝手に絞らない)。

出典: 国土交通省 国土数値情報(観光資源データ 2014 年版)
      https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P12-2014.html
利用条件: 国土数値情報 利用約款(出典明示)
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shapefile  # pyshp

from etl.common import DATA, RAW, ensure_p12, write_json

SHP_GLOB = str(RAW / "ksj" / "P12" / "P12a-14_*.shp")
OUT = DATA / "onsen.geojson"

CATEGORY_ONSEN_HEALTH = "3"  # コードリスト tourismResourceCategoryCd: 3 = 温泉・健康
KIND_ONSEN = "温泉"          # 観光資源台帳の種別名称

# 公開データに存在しない項目。値を作らず null のまま出す(SPEC G-03)。
UNAVAILABLE = ("spring_quality", "temperature_c", "discharge_l_min", "ph",
               "spring_type", "source_depth_m")

PREF_NAMES = [
    "", "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県",
    "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県",
    "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県",
    "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
    "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]


def clean(v) -> str:
    return str(v).replace("\x00", "").strip()


def build() -> dict:
    ensure_p12()
    features = []
    scanned = 0
    for path in sorted(glob.glob(SHP_GLOB)):
        reader = shapefile.Reader(path, encoding="cp932")
        names = [f[0] for f in reader.fields[1:]]
        for sr in reader.iterShapeRecords():
            scanned += 1
            rec = dict(zip(names, sr.record))
            kind = clean(rec["P12_005"])
            code = clean(rec["P12_007"])
            by_kind = kind == KIND_ONSEN
            by_code = code == CATEGORY_ONSEN_HEALTH
            if not (by_kind or by_code):
                continue
            if not sr.shape.points:
                raise SystemExit(f"座標を持たない点がある: {path} {rec}")
            lon, lat = sr.shape.points[0]
            pref = clean(rec["P12_003"])
            name = clean(rec["P12_002"])
            source_id = clean(rec["P12_001"])
            props = {
                # P12 の観光資源_ID は一意ではない(実測 2026-09-07: 秋田県 10297
                # 「湯ノ沢温泉・横堀温泉」が座標違いで 2 レコード)。
                # 元 ID は source_id に残し、こちらで連番を付けて一意にする。
                "onsen_id": f"p12-{pref}-{source_id}",
                "source_id": source_id,
                "name": name,
                "prefecture_code": pref,
                "prefecture": PREF_NAMES[int(pref)] if pref.isdigit() else None,
                "city_code": clean(rec["P12_004"]),
                "address": clean(rec["P12_006"]) or None,
                "kind_name": kind if kind and kind != "‐" else None,
                "category_code": code,
                # 採録経路。どちらの規則で入ったかを残す(後から絞り直せるように)
                "matched_by": ("kind" if by_kind else "") + ("+code" if by_code and by_kind else ("code" if by_code else "")),
                "name_has_onsen": ("温泉" in name) or ("湯" in name),
            }
            props.update({k: None for k in UNAVAILABLE})
            features.append({
                "type": "Feature",
                "id": props["onsen_id"],
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": props,
            })

    # 同一 ID の重複に連番を振って一意にする(元 ID は source_id に保持)
    seen: dict[str, int] = {}
    duplicated = 0
    for f in features:
        base = f["properties"]["onsen_id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            duplicated += 1
            new = f"{base}#{seen[base]}"
            f["properties"]["onsen_id"] = new
            f["id"] = new
    ids = [f["id"] for f in features]
    if len(ids) != len(set(ids)):
        raise SystemExit("一意化に失敗した")

    by_pref = {}
    for f in features:
        by_pref[f["properties"]["prefecture_code"]] = by_pref.get(f["properties"]["prefecture_code"], 0) + 1
    empty = [f"{i:02d}" for i in range(1, 48) if by_pref.get(f"{i:02d}", 0) == 0]

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "国土交通省 国土数値情報",
            "dataset": "観光資源データ(P12) 2014年(平成26年)版",
            "source_url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P12-2014.html",
            "license": "国土数値情報 利用約款(出典明示)",
            "license_url": "https://nlftp.mlit.go.jp/ksj/other/agreement.html",
            "download_date": "2026-09-07",
            "crs_source": "JGD2000 地理座標(.prj 実測)",
            "processing_method": (
                f"P12a(点) 全国 {scanned} 点のうち、種別名称=='温泉' または 観光資源分類コード=='3'(温泉・健康) を抽出"
            ),
            "counts": {
                "scanned_points": scanned,
                "extracted": len(features),
                "by_kind_only": sum(1 for f in features if f["properties"]["matched_by"] == "kind"),
                "by_code_only": sum(1 for f in features if f["properties"]["matched_by"] == "code"),
                "by_both": sum(1 for f in features if f["properties"]["matched_by"] == "kind+code"),
                "name_has_onsen": sum(1 for f in features if f["properties"]["name_has_onsen"]),
                "deduplicated_ids": duplicated,
                "prefectures_with_zero": empty,
            },
            "known_gaps": (
                "観光地点等名簿の提出状況により被覆に偏りがある。"
                f"{len(empty)} 都道府県に 1 点も無い。"
            ),
            "unavailable_fields": list(UNAVAILABLE),
        },
    }


if __name__ == "__main__":
    fc = build()
    write_json(OUT, fc)
    c = fc["metadata"]["counts"]
    print(f"{OUT}: {c['extracted']} 点 / 走査 {c['scanned_points']} 点")
    print(f"  種別のみ {c['by_kind_only']} / コードのみ {c['by_code_only']} / 両方 {c['by_both']}")
    print(f"  名称に温泉・湯を含む {c['name_has_onsen']}")
    print(f"  0 件の都道府県 {len(c['prefectures_with_zero'])}: {c['prefectures_with_zero']}")
