/**
 * クリックで拾った点の候補の並べ方(SPEC G-24)。
 *
 * 点が重なっていると、画素 1 点の問い合わせでは上に描かれた層の点しか選べず、
 * 下の層(たとえば国土数値情報の温泉)に届かなかった。1 つの層を優先すると今度は別の層が隠れるので、
 * 候補が複数なら一覧を出して選ばせる。その一覧の中身をここで固定する。
 *
 * - 同じ地物がタイル境界で二重に返っても、一覧には 1 回だけ出す(層と ID で重複を落とす)
 * - クリック位置に近い順。距離が同じなら層の順(国土数値情報 → Wikidata 温泉 → 入浴施設 → Wikipedia → 火山)
 * - 半径の外の点は候補にしない
 * - 1 件なら一覧を出さずにそのまま開く、0 件なら何も出さない(判定は needsChooser)
 */
import { describe, it, expect } from 'vitest';
import {
  collectCandidates, dotRadiusPx, needsChooser, pickCandidates, radiusExpression, LAYER_ORDER, type RawHit,
} from '../lib/pick';

const hit = (layer: string, id: string, x: number, y: number, name = id): RawHit => ({
  layerId: layer,
  properties: { onsen_id: id, name },
  px: [x, y],
});

describe('候補の集め方', () => {
  it('同じ地物が二重に返っても 1 回だけ', () => {
    const c = collectCandidates([hit('onsen', 'a', 10, 10), hit('onsen', 'a', 10, 10)], [10, 10], 6);
    expect(c.map((x) => x.key)).toEqual(['onsen:a']);
  });

  it('同じ ID でも層が違えば別の候補(出所が違う点は別物)', () => {
    const c = collectCandidates([hit('onsen', 'x', 10, 10), hit('onsen-wd', 'x', 10, 10)], [10, 10], 6);
    expect(c.map((x) => x.key)).toEqual(['onsen:x', 'onsen-wd:x']);
  });

  it('近い順に並べ、同じ距離なら層の順', () => {
    const c = collectCandidates([
      hit('onsen-wp', 'p', 10, 10),
      hit('volcano', 'v', 13, 10),
      hit('onsen-wd', 'w', 10, 10),
      hit('onsen', 'k', 10, 10),
      hit('onsen-fac', 'f', 11, 10),
    ], [10, 10], 6);
    expect(c.map((x) => x.key)).toEqual(['onsen:k', 'onsen-wd:w', 'onsen-wp:p', 'onsen-fac:f', 'volcano:v']);
  });

  it('層の順は国土数値情報 → Wikidata 温泉 → 入浴施設 → Wikipedia → 火山', () => {
    expect(LAYER_ORDER).toEqual(['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp', 'volcano']);
  });

  it('半径の外の点は候補にしない', () => {
    const c = collectCandidates([hit('onsen', 'near', 12, 10), hit('onsen', 'far', 30, 10)], [10, 10], 6);
    expect(c.map((x) => x.key)).toEqual(['onsen:near']);
  });

  it('ID が無い地物(火山など)は名前と座標で区別する', () => {
    const v1: RawHit = { layerId: 'volcano', properties: { name: '富士山' }, px: [5, 5] };
    const v2: RawHit = { layerId: 'volcano', properties: { name: '富士山' }, px: [5, 5] };
    const v3: RawHit = { layerId: 'volcano', properties: { name: '箱根山' }, px: [6, 5] };
    const c = collectCandidates([v1, v2, v3], [5, 5], 6);
    expect(c.map((x) => x.name)).toEqual(['富士山', '箱根山']);
  });
});

describe('押した位置の下にある点だけで一覧を作る', () => {
  // 箱で集めた候補には「近くにあるだけ」の点も入る。それを一覧に出すと、1 つの点をはっきり押しても
  // 一覧が出てしまう(温泉比較で B を選べなくなった)。一覧は**カーソルの下に重なっている点**だけで作り、
  // 下に何も無い押し損ねのときは、箱の中でいちばん近い 1 点を開く。
  // pickCandidates(下にある点, 近くの点, 押した位置, 近くを探す半径 px)。
  // 「下にある」かどうかは**地図の描画系そのもの**に問う(画素 1 点の queryRenderedFeatures)。
  // 半径を自前で計算して判定すると、描画の当たり判定と 1px 前後ずれ、重ならない点を押しても
  // 一覧が出た(実測: 縮尺 9.2 で 40 点中 10 点)。近くの点は、下に何も無いときだけ使う。
  it('下に 2 つ重なっていれば、その 2 つ(近くの点は見ない)', () => {
    const c = pickCandidates(
      [hit('onsen', 'a', 10, 10), hit('onsen-wd', 'b', 11, 10)],
      [hit('onsen', 'a', 10, 10), hit('onsen-wd', 'b', 11, 10), hit('onsen', 'near', 18, 10)],
      [10, 10], 12,
    );
    expect(c.map((x) => x.key)).toEqual(['onsen:a', 'onsen-wd:b']);
  });

  it('下にある 1 つと、近くにあるだけの 1 つなら、下にある 1 つだけ(一覧を出さない)', () => {
    const c = pickCandidates([hit('onsen', 'under', 10, 10)], [hit('onsen', 'under', 10, 10), hit('onsen', 'near', 14, 10)], [10, 10], 12);
    expect(c.map((x) => x.key)).toEqual(['onsen:under']);
    expect(needsChooser(c)).toBe(false);
  });

  it('下に何も無い押し損ねなら、近くの点のうちいちばん近い 1 点', () => {
    const c = pickCandidates([], [hit('onsen', 'n1', 18, 10), hit('onsen-wd', 'n2', 21, 10)], [10, 10], 12);
    expect(c.map((x) => x.key)).toEqual(['onsen:n1']);
  });

  it('下にも近くにも無ければ空', () => {
    expect(pickCandidates([], [hit('onsen', 'far', 40, 10)], [10, 10], 12)).toEqual([]);
  });

  it('同じ地物が下の問い合わせで二重に返っても一覧を出さない', () => {
    const c = pickCandidates([hit('onsen', 'a', 10, 10), hit('onsen', 'a', 10, 10)], [], [10, 10], 12);
    expect(needsChooser(c)).toBe(false);
  });

  it('点の半径は層と縮尺で決まる(地図の描画と同じ段)', () => {
    expect(dotRadiusPx('onsen', 5)).toBeCloseTo(2.4, 9);
    expect(dotRadiusPx('onsen', 10)).toBeCloseTo(4.6, 9);
    expect(dotRadiusPx('onsen', 14)).toBeCloseTo(7, 9);
    expect(dotRadiusPx('onsen', 12)).toBeCloseTo(4.6 + (7 - 4.6) * 0.5, 9);
    expect(dotRadiusPx('onsen', 3)).toBeCloseTo(2.4, 9);    // 段の外は端の値
    expect(dotRadiusPx('volcano', 10)).toBeCloseTo(6.5, 9);
  });

  it('地図の半径の式が段から作られる(描画と判定の定義を 1 か所に置く)', () => {
    expect(radiusExpression('onsen')).toEqual(['interpolate', ['linear'], ['zoom'], 5, 2.4, 10, 4.6, 14, 7]);
    expect(radiusExpression('volcano')).toEqual(['interpolate', ['linear'], ['zoom'], 5, 3.2, 10, 6.5, 14, 9]);
  });
});

describe('一覧を出すかどうか', () => {
  it('0 件は出さない・1 件はそのまま開く・2 件以上で一覧', () => {
    expect(needsChooser([])).toBe(false);
    expect(needsChooser(collectCandidates([hit('onsen', 'a', 1, 1)], [1, 1], 6))).toBe(false);
    expect(needsChooser(collectCandidates([hit('onsen', 'a', 1, 1), hit('onsen-wd', 'b', 1, 1)], [1, 1], 6))).toBe(true);
  });

  it('同じ地物の二重返りだけなら一覧を出さない', () => {
    expect(needsChooser(collectCandidates([hit('onsen', 'a', 1, 1), hit('onsen', 'a', 1, 1)], [1, 1], 6))).toBe(false);
  });
});
