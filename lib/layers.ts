/** レイヤーの定義。出典とライセンスをレイヤーと同じ場所に置く(SPEC F-11)。 */

export type RasterLayer = {
  id: string;
  label: string;
  kind: 'raster';
  url: string;
  attribution: string;
  minzoom?: number;
  maxzoom?: number;
  defaultVisible: boolean;
  defaultOpacity: number;
  note?: string;
};

export type VectorLayer = {
  id: string;
  label: string;
  kind: 'vector';
  data: string;
  attribution: string;
  defaultVisible: boolean;
  defaultOpacity: number;
  note?: string;
};

export type Layer = RasterLayer | VectorLayer;

const GSI = '国土地理院';
const GSJ = '産総研 地質調査総合センター「20万分の1日本シームレス地質図V2」';

/** ベースマップ(排他選択) */
export const BASEMAPS: RasterLayer[] = [
  {
    id: 'pale', label: '淡色地図', kind: 'raster',
    url: 'https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png',
    attribution: GSI, maxzoom: 18, defaultVisible: true, defaultOpacity: 1,
  },
  {
    id: 'std', label: '標準地図', kind: 'raster',
    url: 'https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png',
    attribution: GSI, maxzoom: 18, defaultVisible: false, defaultOpacity: 1,
  },
  {
    id: 'blank', label: '白地図(地形だけを見る)', kind: 'raster',
    url: 'https://cyberjapandata.gsi.go.jp/xyz/blank/{z}/{x}/{y}.png',
    attribution: GSI, maxzoom: 14, defaultVisible: false, defaultOpacity: 1,
  },
];

/** 重ねるラスタ */
export const OVERLAYS: RasterLayer[] = [
  {
    id: 'relief', label: '色別標高図', kind: 'raster',
    url: 'https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png',
    attribution: GSI, maxzoom: 15, defaultVisible: false, defaultOpacity: 0.6,
    note: '標高を色で塗り分けた図。凡例は地理院の配色に従う',
  },
  {
    id: 'hillshade', label: '陰影起伏図', kind: 'raster',
    url: 'https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png',
    attribution: GSI, maxzoom: 16, defaultVisible: true, defaultOpacity: 0.35,
    note: '北西から光を当てた陰影。地形の起伏を読むための図',
  },
  {
    id: 'geology', label: '地質図(シームレス地質図V2)', kind: 'raster',
    url: 'https://gbank.gsj.jp/seamless/v2/api/1.3/tiles/{z}/{y}/{x}.png',
    attribution: GSJ, maxzoom: 13, defaultVisible: false, defaultOpacity: 0.55,
    note: 'クリックすると凡例(地質時代・岩相)を引く。タイル座標が {z}/{y}/{x} の順である点に注意',
  },
];

/** 水のレイヤー(線と面)。出典と利用条件が河川と湖沼で違う点に注意。 */
export const WATER_LAYERS = [
  {
    id: 'rivers', label: '河川(1級河川の直轄区間)', kind: 'vector' as const,
    data: '/data/rivers.geojson',
    attribution: '国土交通省 国土数値情報 河川データ(W05・非商用限定)',
    defaultVisible: false, defaultOpacity: 0.85,
    note: '地図に描くのは国が直接管理する区間だけ。温泉からの距離は全 286,437 区間で測っている',
  },
  {
    id: 'lakes', label: '湖沼', kind: 'vector' as const,
    data: '/data/lakes.geojson',
    attribution: '国土交通省 国土数値情報 湖沼データ(W09)',
    defaultVisible: false, defaultOpacity: 0.55,
    note: '全 556 面。表示用に頂点を間引いてある',
  },
];

export const CONTOUR_INTERVALS = [10, 20, 50, 100, 200, 500] as const;
export const DEFAULT_CONTOUR_INTERVAL = 100;

/** 等高線を引くのに使う標高タイル。dem_png は z8–z14 に存在する(実測 2026-09-07)。 */
export const DEM = {
  url: 'https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png',
  minzoom: 8,
  maxzoom: 14,
  attribution: `${GSI} 標高タイル(dem_png)`,
};

export const GEOLOGY_LEGEND_API = 'https://gbank.gsj.jp/seamless/v2/api/1.3/legend.json';

export const SOURCES = [
  { name: '国土地理院', what: '地図タイル・陰影起伏・色別標高・標高タイル', url: 'https://maps.gsi.go.jp/development/ichiran.html', license: '国土地理院コンテンツ利用規約', licenseUrl: 'https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html' },
  { name: '産業技術総合研究所 地質調査総合センター', what: '20万分の1日本シームレス地質図V2(タイル・凡例 API)', url: 'https://gbank.gsj.jp/seamless/', license: '政府標準利用規約(第2.0版)', licenseUrl: 'https://gbank.gsj.jp/seamless/use.html' },
  { name: '気象庁', what: '活火山の一覧と位置', url: 'https://www.jma.go.jp/bosai/volcano/', license: '気象庁ホームページの利用について', licenseUrl: 'https://www.jma.go.jp/jma/kishou/info/coment.html' },
  { name: '国土交通省 国土数値情報', what: '観光資源データ(P12, 2014年版)から抽出した温泉点', url: 'https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P12-2014.html', license: '国土数値情報 利用約款', licenseUrl: 'https://nlftp.mlit.go.jp/ksj/other/agreement.html' },
  { name: '国土交通省 国土数値情報(河川)', what: '河川データ(W05)。地図表示は1級河川の直轄区間、距離は全区間', url: 'https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html', license: '国土数値情報 利用約款（非商用限定）', licenseUrl: 'https://nlftp.mlit.go.jp/ksj/other/agreement.html' },
  { name: '国土交通省 国土数値情報(湖沼)', what: '湖沼データ(W09, 2005年版)', url: 'https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W09-v2_2.html', license: '国土数値情報 利用約款', licenseUrl: 'https://nlftp.mlit.go.jp/ksj/other/agreement.html' },
] as const;

/** 設計書 §36 の免責。表現をここに固定し、画面から必ず参照する。 */
export const DISCLAIMER =
  'この地図と集計は公開データをそのまま重ねたものです。温泉の存在・泉質・湧出量を保証するものではありません。';
