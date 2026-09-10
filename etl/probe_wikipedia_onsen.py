"""日本語版 Wikipedia の温泉記事から、地図に足せる点がどれだけあるかを**測る**。

これは出荷用の ETL ではなく、**採るかどうかを決めるための実測**である。

## 何を知りたいか

利用者から「山中湖温泉・大田区の黒湯温泉などが地図に無い。Wikipedia から辿れないか」
と指摘があった。まず 3 件を調べたところ、**落ちる理由が三つとも違った**。

| 記事 | Wikidata | 分類 | 座標 | 落ちた理由 |
|---|---|---|---|---|
| ほったらかし温泉 | Q11277778 | 日帰り入浴施設 | 有 | 分類が温泉でない(loop_008 で第三の層に追加) |
| 大田区の黒湯温泉 | Q671405 | **温泉** | **無** | 分類は合うが**座標が無い** |
| 山中湖温泉 | **無し** | — | **無** | **項目自体が無い** |

そこで、Wikipedia のカテゴリ「日本の温泉」を辿って全記事を集め、

1. 記事または Wikidata に**座標があるものが何件か**
2. そのうち**今の 3 層のどれにも無い場所が何件か**(= 足して増える数)
3. **座標が無いものが何件か**(= 辿っても地図には載せられない数)

を数える。座標が無いものは、**緯度経度を作れば地図に出せる**が、それは
架空のデータを作ることであり設計書 §71/§72 が禁じている。数だけを記録する。

## 利用条件

日本語版 Wikipedia の本文は **CC BY-SA 4.0**。この地図の既存データ(CC0・政府の利用約款)
とは条件が違う。採るなら出典表示と継承の扱いを別に立てる必要がある。
このプローブは**数を測るだけ**で、本文は保存しない(記事名・座標・Wikidata の ID のみ)。

使い方: python etl/probe_wikipedia_onsen.py
出力: logs/wikipedia_onsen_probe.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.common import DATA, REPO, UA, haversine_km

API = "https://ja.wikipedia.org/w/api.php"

# 入口は**都道府県別**である。最初「Category:日本の温泉」から辿ろうとして 0 件を得たが、
# そのカテゴリは**存在しない**。カテゴリが在ることを確かめずに 0 を読むと、
# 「無い」と「入口が違う」を取り違える。ROOTS の実在は collect_articles で確認する。
PREFS = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県",
    "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県",
    "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県",
    "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
    "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
ROOTS = [f"Category:{p}の温泉" for p in PREFS]
# 深さは環境変数で変える。**取り込み時に sys.argv を読まない** ——
# pytest から import したとき、テストのファイル名を深さとして解釈して落ちた。
MAX_DEPTH = int(os.environ.get("WP_PROBE_DEPTH", "0"))
SLEEP = 0.25          # 外部への過剰アクセスを避ける(設計書 §44)
BATCH = 50            # API の上限
NEAR_KM = 0.3         # 既存の点と「同じ場所」とみなす距離(既存層の重なり判定と同じ)
OUT = REPO / "logs" / "wikipedia_onsen_probe.json"   # 深さごとに上書きせず名前を変える


def api(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.load(r)
            time.sleep(SLEEP)
            return body
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("到達しない")


def category_members(title: str, kind: str) -> list[str]:
    """カテゴリの直下にある記事(kind='page')か下位カテゴリ(kind='subcat')。"""
    out, cont = [], None
    while True:
        p = {"action": "query", "list": "categorymembers", "cmtitle": title,
             "cmlimit": "500", "cmtype": kind,
             # cmtype=page は Template: なども拾う(実測: Template:Arima onsen 等が
             # 混ざっていた)。**記事の名前空間だけ**に絞る
             "cmnamespace": "0" if kind == "page" else "14"}
        if cont:
            p["cmcontinue"] = cont
        d = api(p)
        out += [m["title"] for m in d.get("query", {}).get("categorymembers", [])]
        cont = d.get("continue", {}).get("cmcontinue")
        if not cont:
            return out


def exists(titles: list[str]) -> list[str]:
    """存在するものだけを返す。**入口が在ることを確かめてから数える。**"""
    ok = []
    for i in range(0, len(titles), BATCH):
        d = api({"action": "query", "prop": "info", "titles": "|".join(titles[i:i + BATCH])})
        for p in d["query"]["pages"]:
            if not p.get("missing"):
                ok.append(p["title"])
    return ok


def collect_articles() -> tuple[list[str], list[str]]:
    """カテゴリ木を深さ MAX_DEPTH まで辿って記事名を集める。"""
    roots = exists(ROOTS)
    missing = sorted(set(ROOTS) - set(roots))
    if missing:
        print(f"  存在しない入口 {len(missing)} 件: {missing[:5]}")
    if not roots:
        raise SystemExit("入口のカテゴリが 1 つも存在しない。名前が違う")
    print(f"  入口 {len(roots)}/{len(ROOTS)} カテゴリ")

    seen_cat, articles = set(roots), set()
    frontier = [(c, 0) for c in roots]
    while frontier:
        cat, depth = frontier.pop(0)
        for a in category_members(cat, "page"):
            articles.add(a)
        if depth < MAX_DEPTH:
            for sub in category_members(cat, "subcat"):
                if sub not in seen_cat:
                    seen_cat.add(sub)
                    frontier.append((sub, depth + 1))
    print(f"  カテゴリ {len(seen_cat)} / 記事 {len(articles)}")
    return sorted(articles), sorted(seen_cat)


def article_info(titles: list[str]) -> dict[str, dict]:
    """記事ごとの座標と Wikidata の ID。"""
    info: dict[str, dict] = {}
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        d = api({"action": "query", "prop": "pageprops|coordinates",
                 "coprop": "type", "colimit": "max", "titles": "|".join(chunk)})
        for p in d.get("query", {}).get("pages", []):
            coords = p.get("coordinates") or []
            info[p["title"]] = {
                "qid": (p.get("pageprops") or {}).get("wikibase_item"),
                "lat": coords[0]["lat"] if coords else None,
                "lon": coords[0]["lon"] if coords else None,
            }
        print(f"  座標を照会 {min(i + BATCH, len(titles))}/{len(titles)}")
    return info


def wikidata_coords(qids: list[str]) -> dict[str, tuple[float, float]]:
    """記事に座標が無いものについて、Wikidata 側に座標があるかを見る。"""
    out: dict[str, tuple[float, float]] = {}
    for i in range(0, len(qids), 200):
        chunk = qids[i:i + 200]
        values = " ".join(f"wd:{q}" for q in chunk)
        q = f"SELECT ?x ?coord WHERE {{ VALUES ?x {{ {values} }} ?x wdt:P625 ?coord . }}"
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
            {"query": q, "format": "json"})
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            rows = json.load(r)["results"]["bindings"]
        for b in rows:
            lon, lat = b["coord"]["value"].replace("Point(", "").replace(")", "").split()
            out[b["x"]["value"].rsplit("/", 1)[-1]] = (float(lon), float(lat))
        time.sleep(SLEEP)
        print(f"  Wikidata の座標を照会 {min(i + 200, len(qids))}/{len(qids)}")
    return out


def existing_points() -> list[tuple[float, float]]:
    pts = []
    for f in ("onsen.geojson", "onsen_wikidata.geojson", "onsen_facility.geojson"):
        d = json.loads((DATA / f).read_text(encoding="utf-8"))
        pts += [tuple(x["geometry"]["coordinates"]) for x in d["features"]]
    return pts


def main() -> None:
    print("カテゴリ木を辿る…")
    articles, cats = collect_articles()
    print(f"記事 {len(articles)} 件 / カテゴリ {len(cats)} 件")

    print("記事の座標と Wikidata の ID を引く…")
    info = article_info(articles)

    # 記事に座標が無く、Wikidata の ID がある分だけ Wikidata を見る
    need = [v["qid"] for v in info.values() if v["lat"] is None and v["qid"]]
    print(f"記事に座標が無く Wikidata の ID がある: {len(need)} 件")
    wd = wikidata_coords(need) if need else {}

    rows = []
    for title, v in info.items():
        lon, lat, src = v["lon"], v["lat"], "wikipedia"
        if lat is None and v["qid"] in wd:
            lon, lat = wd[v["qid"]]
            src = "wikidata"
        rows.append({"title": title, "qid": v["qid"],
                     "lon": lon, "lat": lat,
                     "coord_source": src if lat is not None else None})

    have = [r for r in rows if r["lat"] is not None]
    none = [r for r in rows if r["lat"] is None]

    pts = existing_points()
    new = [r for r in have
           if not any(haversine_km(r["lon"], r["lat"], p[0], p[1]) <= NEAR_KM for p in pts)]

    summary = {
        "root_categories": len(ROOTS),
        "max_depth": MAX_DEPTH,
        "categories": len(cats),
        "articles": len(articles),
        "with_coordinates": len(have),
        "coord_from_wikipedia": sum(1 for r in have if r["coord_source"] == "wikipedia"),
        "coord_from_wikidata": sum(1 for r in have if r["coord_source"] == "wikidata"),
        "without_coordinates": len(none),
        "without_wikidata_item": sum(1 for r in rows if not r["qid"]),
        "new_locations": len(new),
        "near_km": NEAR_KM,
        "existing_points": len(pts),
        "license_note": "ja.wikipedia の本文は CC BY-SA 4.0。既存データ(CC0・政府の利用約款)と条件が違う",
    }
    out = OUT.with_name(f"wikipedia_onsen_probe_d{MAX_DEPTH}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"summary": summary,
         "sample_new": [r["title"] for r in new[:40]],
         "sample_without_coordinates": [r["title"] for r in none[:40]],
         "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
