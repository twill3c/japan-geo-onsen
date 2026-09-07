'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  BASEMAPS, CONTOUR_INTERVALS, DEFAULT_CONTOUR_INTERVAL, DEM,
  GEOLOGY_LEGEND_API, OVERLAYS, WATER_LAYERS,
} from '@/lib/layers';
import { buildContours, demZoomFor } from '@/lib/contour-tiles';
import FeaturePanel, { type Selection } from '@/components/FeaturePanel';
import LayerControl from '@/components/LayerControl';

/** 初期表示は八ヶ岳周辺(設計書 §59 の実証地域)。 */
const INITIAL = { center: [138.35, 35.98] as [number, number], zoom: 9.2 };

export default function MapView() {
  const holder = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);

  const [basemap, setBasemap] = useState('pale');
  const [visible, setVisible] = useState<Record<string, boolean>>(() => {
    const v: Record<string, boolean> = { onsen: true, volcano: true };
    for (const o of OVERLAYS) v[o.id] = o.defaultVisible;
    for (const w of WATER_LAYERS) v[w.id] = w.defaultVisible;
    return v;
  });
  const [opacity, setOpacity] = useState<Record<string, number>>(() => {
    const v: Record<string, number> = { onsen: 0.9, volcano: 0.9 };
    for (const o of OVERLAYS) v[o.id] = o.defaultOpacity;
    for (const w of WATER_LAYERS) v[w.id] = w.defaultOpacity;
    return v;
  });

  const [contourOn, setContourOn] = useState(false);
  const [interval, setIntervalM] = useState<number>(DEFAULT_CONTOUR_INTERVAL);
  const [contourNote, setContourNote] = useState('');
  const [onsenNameOnly, setOnsenNameOnly] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [tileError, setTileError] = useState<string | null>(null);
  const contourRun = useRef(0);

  /* ---- 地図ページの間だけ、画面の高さを確定させる ---- */
  useEffect(() => {
    document.body.classList.add('map-mode');
    return () => { document.body.classList.remove('map-mode'); };
  }, []);

  /* ---- 地図の生成 ---- */
  useEffect(() => {
    if (!holder.current || map.current) return;
    const m = new maplibregl.Map({
      container: holder.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#e9e6dd' } }],
      },
      center: INITIAL.center,
      zoom: INITIAL.zoom,
      maxZoom: 17,
      minZoom: 4,
      attributionControl: false,
      // 描画バッファを残す。これが false だと WebGL 面はスクリーンショットに写らず、
      // 「地図が真っ白」という**偽の異常**が出る(実測 2026-09-07)。
      // 実ブラウザ検品を目で確かめられることを、わずかな描画コストより優先する。
      // MapLibre 5 では canvasContextAttributes 経由で渡す
      canvasContextAttributes: { preserveDrawingBuffer: true, antialias: true },
    });
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right');
    m.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-right');
    // 出典は地図の上にも出す(設計書 §46)。左の一覧と /about/ にも同じものがある
    m.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');

    // 外部タイルが落ちてもアプリ本体は生かす(SPEC N-03 / 設計書 §66)
    m.on('error', (e) => {
      const msg = (e as { error?: { message?: string } }).error?.message ?? '';
      if (/tile|fetch|load|network/i.test(msg)) {
        setTileError('一部のデータを取得できませんでした（外部の地図サービス側の問題の可能性があります）');
      }
    });

    m.on('load', () => {
      for (const b of BASEMAPS) {
        m.addSource(b.id, {
          type: 'raster', tiles: [b.url], tileSize: 256,
          maxzoom: b.maxzoom ?? 18, attribution: b.attribution,
        });
        m.addLayer({
          id: b.id, type: 'raster', source: b.id,
          layout: { visibility: b.id === 'pale' ? 'visible' : 'none' },
        });
      }
      for (const o of OVERLAYS) {
        m.addSource(o.id, {
          type: 'raster', tiles: [o.url], tileSize: 256,
          maxzoom: o.maxzoom ?? 18, attribution: o.attribution,
        });
        m.addLayer({
          id: o.id, type: 'raster', source: o.id,
          layout: { visibility: o.defaultVisible ? 'visible' : 'none' },
          paint: { 'raster-opacity': o.defaultOpacity },
        });
      }

      // 水(河川 2.1 MB・湖沼 0.65 MB)は既定で消えている。ここで読み込むと、
      // 見ない人にも 2.85 MB を配ることになる。**点けたときに初めて足す**。
      m.addSource('contours', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      m.addLayer({
        id: 'contours', type: 'line', source: 'contours',
        layout: { visibility: 'none', 'line-join': 'round' },
        paint: {
          'line-color': '#5b4a33',
          'line-width': ['case', ['get', 'major'], 1.4, 0.6],
          'line-opacity': ['case', ['get', 'major'], 0.85, 0.5],
        },
      });

      m.addSource('volcano', { type: 'geojson', data: '/data/volcanoes.geojson' });
      m.addLayer({
        id: 'volcano', type: 'circle', source: 'volcano',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3.2, 10, 6.5, 14, 9],
          'circle-color': ['case', ['get', 'warning_level_operated'], '#991b1b', '#b45309'],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1,
          'circle-opacity': 0.9,
        },
      });
      m.addLayer({
        id: 'volcano-label', type: 'symbol', source: 'volcano', minzoom: 8,
        layout: {
          'text-field': ['get', 'name'], 'text-size': 11,
          'text-offset': [0, 1.1], 'text-anchor': 'top',
        },
        paint: { 'text-color': '#7f1d1d', 'text-halo-color': '#ffffff', 'text-halo-width': 1.4 },
      });

      m.addSource('onsen', { type: 'geojson', data: '/data/onsen.geojson' });
      m.addLayer({
        id: 'onsen', type: 'circle', source: 'onsen',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 2.4, 10, 4.6, 14, 7],
          'circle-color': '#c2410c',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 0.8,
          'circle-opacity': 0.9,
        },
      });
      m.addLayer({
        id: 'onsen-label', type: 'symbol', source: 'onsen', minzoom: 11,
        layout: {
          'text-field': ['get', 'name'], 'text-size': 10.5,
          'text-offset': [0, 0.9], 'text-anchor': 'top',
        },
        paint: { 'text-color': '#7c2d12', 'text-halo-color': '#ffffff', 'text-halo-width': 1.3 },
      });

      for (const id of ['onsen', 'volcano']) {
        m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer'; });
        m.on('mouseleave', id, () => { m.getCanvas().style.cursor = ''; });
      }
      // 置き場の高さが確定する前に構築されると既定寸法のまま固まるので、
      // 読み込み後に必ず測り直させる(実測 2026-09-07: 774px の枠に 300px の canvas)。
      m.resize();
      // 実ブラウザ検品から描画済みフィーチャを数えるための口(harness/smoke.mjs)。
      // 検品器が「地図が出た」ではなく「点が実際に描かれた」を見られるようにする。
      (window as unknown as { __map?: maplibregl.Map }).__map = m;
      setReady(true);
    });

    // 置き場の大きさが変わったら追随する(MapLibre の trackResize だけに任せない)
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(holder.current);

    map.current = m;
    return () => { ro.disconnect(); m.remove(); map.current = null; };
  }, []);

  /* ---- ベースマップの切替 ---- */
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    for (const b of BASEMAPS) {
      m.setLayoutProperty(b.id, 'visibility', b.id === basemap ? 'visible' : 'none');
    }
  }, [basemap, ready]);

  /* ---- 重ねるレイヤーの表示と不透明度 ---- */
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    for (const o of OVERLAYS) {
      m.setLayoutProperty(o.id, 'visibility', visible[o.id] ? 'visible' : 'none');
      m.setPaintProperty(o.id, 'raster-opacity', opacity[o.id]);
    }
    // 水は初めて点けたときに足す(起動時に読まない)。地形の上・等高線の下に入れる。
    if (visible.lakes && !m.getLayer('lakes')) {
      m.addSource('lakes', { type: 'geojson', data: '/data/lakes.geojson' });
      m.addLayer({
        id: 'lakes', type: 'fill', source: 'lakes',
        paint: { 'fill-color': '#3b82c4', 'fill-opacity': opacity.lakes, 'fill-outline-color': '#1f5b91' },
      }, 'contours');
    }
    if (visible.rivers && !m.getLayer('rivers')) {
      m.addSource('rivers', { type: 'geojson', data: '/data/rivers.geojson' });
      m.addLayer({
        id: 'rivers', type: 'line', source: 'rivers',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': '#2a6fb0',
          'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.6, 9, 1.3, 14, 2.6],
          'line-opacity': opacity.rivers,
        },
      }, 'contours');
    }
    if (m.getLayer('rivers')) {
      m.setLayoutProperty('rivers', 'visibility', visible.rivers ? 'visible' : 'none');
      m.setPaintProperty('rivers', 'line-opacity', opacity.rivers);
    }
    if (m.getLayer('lakes')) {
      m.setLayoutProperty('lakes', 'visibility', visible.lakes ? 'visible' : 'none');
      m.setPaintProperty('lakes', 'fill-opacity', opacity.lakes);
    }
    const pairs: [string, string][] = [['onsen', 'onsen-label'], ['volcano', 'volcano-label']];
    for (const [id, labelId] of pairs) {
      const vis = visible[id] ? 'visible' : 'none';
      m.setLayoutProperty(id, 'visibility', vis);
      m.setLayoutProperty(labelId, 'visibility', vis);
      m.setPaintProperty(id, 'circle-opacity', opacity[id]);
    }
  }, [visible, opacity, ready]);

  /* ---- 温泉の絞り込み(名称に「温泉」「湯」を含むものだけ) ---- */
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const filter = onsenNameOnly
      ? (['==', ['get', 'name_has_onsen'], true] as maplibregl.FilterSpecification)
      : null;
    m.setFilter('onsen', filter);
    m.setFilter('onsen-label', filter);
  }, [onsenNameOnly, ready]);

  /* ---- 等高線 ---- */
  const refreshContours = useCallback(async () => {
    const m = map.current;
    if (!m || !ready) return;
    const src = m.getSource('contours') as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    if (!contourOn) {
      m.setLayoutProperty('contours', 'visibility', 'none');
      setContourNote('');
      return;
    }
    m.setLayoutProperty('contours', 'visibility', 'visible');
    const run = ++contourRun.current;
    setContourNote('標高タイルを読み込み中…');
    const b = m.getBounds();
    const res = await buildContours(
      { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() },
      m.getZoom(), interval,
    );
    if (run !== contourRun.current) return; // 追い越された結果は捨てる
    if (!res.ok) {
      src.setData({ type: 'FeatureCollection', features: [] });
      setContourNote(res.reason);
      return;
    }
    src.setData(res.geojson);
    const miss = res.missing > 0 ? `・取得できなかったタイル ${res.missing} 枚` : '';
    const thin = res.stride > 1 ? `・${res.stride} 画素おきに走査` : '';
    setContourNote(
      `${interval} m 間隔で ${res.levels.length} 本 / 標高タイル z${res.zoom} を ${res.tiles} 枚${thin}${miss}`,
    );
  }, [contourOn, interval, ready]);

  useEffect(() => { void refreshContours(); }, [refreshContours]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let timer: ReturnType<typeof setTimeout>;
    const onMove = () => {
      clearTimeout(timer);
      timer = setTimeout(() => { void refreshContours(); }, 350);
    };
    m.on('moveend', onMove);
    return () => { clearTimeout(timer); m.off('moveend', onMove); };
  }, [refreshContours, ready]);

  /* ---- クリック ---- */
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const onClick = async (e: maplibregl.MapMouseEvent) => {
      const hits = m.queryRenderedFeatures(e.point, { layers: ['onsen', 'volcano'] });
      if (hits.length > 0) {
        const f = hits[0];
        setSelection({
          kind: f.layer.id === 'onsen' ? 'onsen' : 'volcano',
          properties: f.properties ?? {},
        });
        return;
      }
      if (!visible.geology) { setSelection(null); return; }
      const { lng, lat } = e.lngLat;
      setSelection({ kind: 'geology', loading: true, properties: {}, lngLat: [lng, lat] });
      try {
        const r = await fetch(`${GEOLOGY_LEGEND_API}?point=${lat.toFixed(6)},${lng.toFixed(6)}`);
        const d = r.ok ? await r.json() : null;
        setSelection({ kind: 'geology', properties: d ?? {}, lngLat: [lng, lat] });
      } catch {
        setSelection({
          kind: 'geology', properties: {},
          error: '地質の凡例を取得できませんでした', lngLat: [lng, lat],
        });
      }
    };
    m.on('click', onClick);
    return () => { m.off('click', onClick); };
  }, [ready, visible.geology]);

  return (
    <div className="map-shell">
      <LayerControl
        basemap={basemap} setBasemap={setBasemap}
        visible={visible} setVisible={setVisible}
        opacity={opacity} setOpacity={setOpacity}
        contourOn={contourOn} setContourOn={setContourOn}
        interval={interval} setInterval={setIntervalM}
        intervals={CONTOUR_INTERVALS as unknown as number[]}
        water={WATER_LAYERS}
        contourNote={contourNote}
        demZoomNote={`標高タイルは z${DEM.minzoom}–z${DEM.maxzoom} にあります。縮尺に応じて使う段を切り替えます`}
        onsenNameOnly={onsenNameOnly} setOnsenNameOnly={setOnsenNameOnly}
      />
      <div className="map-area">
        <div ref={holder} className="map-canvas" />
        {tileError && <div className="map-toast">{tileError}</div>}
        <FeaturePanel selection={selection} onClose={() => setSelection(null)} />
      </div>
    </div>
  );
}
