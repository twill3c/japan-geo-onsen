# 日本列島 自然環境・温泉GIS

地形・地質・火山・温泉を一枚の地図に重ね、**公開データの範囲で**その関係を実測する
教育・研究・技術実験用の Web GIS。

**本番: https://japan-geo-onsen.vercel.app**

- 地図: MapLibre GL JS
- 外側: Next.js（静的書き出し）— サーバ側の処理はひとつも無い
- データ加工: Python（ETL は手動実行）

## できること

| 画面 | 中身 |
|---|---|
| `/` | 地形・陰影・色別標高・地質・等高線・火山・温泉のレイヤー地図。クリックで属性 |
| `/stats/` | 温泉と**対照群**を、地質・標高・傾斜・火山距離で比べた集計 |
| `/onsen-stats/` | 環境省の温泉利用状況（源泉数・**温度別源泉数**・湧出量）を都道府県別に |
| `/about/` | 出典・利用条件・加工方法と、**探して見つからなかったデータ**の記録 |

等高線は事前に作った線ではなく、**表示範囲の標高タイルをその場で読んで**
marching squares で引いている。

## この地図が出している数

| 対象 | 件数 | 出典 |
|---|---|---|
| 活火山 | 111 | 気象庁 |
| 温泉（観光資源） | 1,320 | 国土交通省 国土数値情報 P12(2014) |
| 対照点 | 1,320 | 同上（温泉以外の観光地点を県ごとに同数抽出） |
| 地質凡例 | 2,416 | 産総研 シームレス地質図V2 |

## 分かったこと（実測 2026-09-07）

- **気象庁の火山一覧 JSON は 120 件あるが、活火山は 111 である。**
  `120 = 111 + 3（座標を持たない一覧表示用の項目）+ 6（親火山の火口細分）`。
  この分解が崩れたらデータ生成は止まる。
- **温泉の泉質・泉温・湧出量を地点ごとに載せた全国の公開データは存在しない。**
  国土数値情報の全 157 データセットに温泉は無く、環境省は都道府県別の集計 PDF のみ。
  よってこれらの欄は **null のまま出荷し、画面には「公開データに無い」と書く**。
- **環境省が数える温泉地 2,839 の一覧は公開されていない。** 集計 PDF に載るのは数だけで、
  名前も座標も無い。だから 2,839 そのものを点にすることはできない。
  被覆を広げるため **Wikidata(CC0)の温泉 1,477 件**を第二の層として足した
  （重複を除いた地点 **2,455**＝温泉地の 86%）。ただし悉皆調査ではないので**統計には使わない**。
- **地形断面は縦を引き伸ばして描くので、倍率を必ず出す。** 上り・下りの合計は刻みの
  細かさで変わる量なので、そのことも書く（起伏は刻みが 1 画素に近ければ落ち着く）。
- **植生自然度で差が出るのは中ほどの段階だけ。** 温泉は市街地・農耕地に少なく（−14.2 pt）、
  植林地・二次林に多い（+7.1 / +8.5 pt）一方、**自然林・自然草原では +0.09 pt** でほぼ差が無い。
- **温泉点の被覆には穴がある。** 10 都府県に 1 点も無い。「点が無い＝温泉が無い」ではない。
  環境省の公表値と並べると、地図の点 **1,320** は温泉地 **2,839** の 46%、源泉 **27,899** の 5% にすぎない。
- **泉温は都道府県別になら実データがある。** 環境省の集計で、温度の記録がある源泉 24,668 のうち
  **51.5% が 42 度以上**。ただし源泉全体の **11.6% は温度が測られていない**。
- 環境省 PDF は抽出テキストでは数字が割れており、**書式では列を決められない割れ方**がある
  （「4」+「7」= 47）。文字の座標で切ると全 47 行が例外なく 20 列になった。
- OpenStreetMap の `amenity=public_bath` 等は全国 5,803 件で被覆は広いが、
  源泉ではなく入浴施設であり、ODbL の継承条件が政府標準利用規約のデータと混ざるため採らなかった。

## 作り直す

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install pyshp Pillow pytest
npm install

# 生データの取得（raw/ にキャッシュされ、二度目からは外部を叩かない）
./.venv/Scripts/python.exe etl/build_volcanoes.py
./.venv/Scripts/python.exe etl/build_onsen_base.py
./.venv/Scripts/python.exe etl/enrich_onsen.py
./.venv/Scripts/python.exe etl/build_onsen_wikidata.py   # 第二の点レイヤー(CC0)
./.venv/Scripts/python.exe etl/enrich_onsen.py onsen_wikidata.geojson
./.venv/Scripts/python.exe etl/build_control.py
./.venv/Scripts/python.exe etl/enrich_onsen.py control.geojson
./.venv/Scripts/python.exe etl/build_water.py     # 河川・湖沼(下記の zip が要る)
./.venv/Scripts/python.exe etl/parse_onsen_stats.py  # 環境省 PDF(都道府県別)
./.venv/Scripts/python.exe etl/build_vegetation.py    # 植生(下記の lzh が要る)
./.venv/Scripts/python.exe etl/make_profile_fixture.py  # 断面の二実装照合フィクスチャ
./.venv/Scripts/python.exe etl/check_elevation.py      # 標高を地理院 標高 API と突き合わせる
./.venv/Scripts/python.exe etl/build_stats.py
./.venv/Scripts/python.exe etl/build_manifest.py

npm run verify     # 型検査 → vitest → next build
node harness/smoke.mjs --shot                              # 実ブラウザ検品(手元)
node harness/smoke.mjs --url https://japan-geo-onsen.vercel.app   # 本番に対する検品
```

### 植生の生データ

```bash
curl -L -o raw/biodic/veg_c02.lzh   https://www.biodic.go.jp/dload/veg_c02.lzh
curl -L -o raw/biodic/veg05m01.lzh  https://www.biodic.go.jp/dload/veg05m01.lzh
"/c/Program Files/7-Zip/7z.exe" x -y -oraw/biodic raw/biodic/veg_c02.lzh
"/c/Program Files/7-Zip/7z.exe" x -y -oraw/biodic raw/biodic/veg05m01.lzh
```

**LZH 形式**なので 7-Zip が要る（Python の標準ライブラリでは開けない）。
展開物はリポジトリに入れていない（配布形の lzh だけを残す）。

### 河川・湖沼の生データ

リポジトリには入れていない（河川は 47 県で **296 MB**）。次で `raw/` に置く。

```bash
# 河川 W05（都道府県別・年版が県ごとに違うので一覧ページから拾う）
#   https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html
# 湖沼 W09（全国 1 ファイル・7.7 MB）
curl -L -o raw/ksj/W09/W09-05_GML.zip   https://nlftp.mlit.go.jp/ksj/gml/data/W09/W09-05/W09-05_GML.zip
```

**河川データ(W05)の利用条件は非商用限定**で、国土数値情報の他のデータとは異なる。

## 配る

`raw/` は 570 MB あり、そのまま送るとアップロードが中断したうえ
Vercel free のファイル枠(5,000)を焼く。`.vercelignore` で除外する。

```bash
vercel deploy --prod --yes
```

**`--archive=tgz` を使ってはならない。** この経路は `.vercelignore` を
ローカルで適用せず、`raw/` を丸ごと詰めて **530 MB** を送ろうとする
(実測 2026-09-08)。archive はファイル数の上限を避ける道具であって、
容量を減らす道具ではない。

**デプロイ中に `npm run build` を走らせない。** 送信元の `out/` が
書き換わると `ENOENT` で落ちる。

**配ったあと、出た版が意図した版かを実測する。** デプロイの終了コードを読み、
`node harness/smoke.mjs --url <本番>` を通し、さらに
配られている JS が意図した実装かを確かめること —— デプロイが失敗していても
古い版が動いているので、画面を見ただけでは気づけない。

**生成はビルドより前に置くこと。** 成果物は `public/data/` に直接書いており、
`data/` から写す段は作っていない（写す段があると、写した後に元を変えたときに
成果物だけが古く残る — HC-199）。

## データ出典

| 提供元 | 使っているもの | 利用条件 |
|---|---|---|
| 国土地理院 | 地図・陰影起伏・色別標高・標高タイル | 国土地理院コンテンツ利用規約 |
| 産業技術総合研究所 地質調査総合センター | 20万分の1日本シームレス地質図V2 | 政府標準利用規約(第2.0版) |
| 気象庁 | 活火山の一覧と位置 | 気象庁ホームページの利用について |
| 国土交通省 | 国土数値情報 観光資源データ(P12) | 国土数値情報 利用約款 |

## 免責

この地図と集計は公開データをそのまま重ねたものです。
温泉の存在・泉質・湧出量を保証するものではありません。
「ここを掘れば温泉が出る」という主張はしません。

## ライセンス

MIT License © 2026 坂田哲朗（コードについて。データは各提供元の条件に従う）
