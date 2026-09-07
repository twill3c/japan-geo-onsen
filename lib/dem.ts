/**
 * 国土地理院 標高タイル(dem_png)の解読と、等高線の生成。
 *
 * 標高の求め方は地理院の仕様に従う。Python 側(etl/common.py の decode_dem_rgb)と
 * **同じ入力に同じ出力**を返すことをテストで照合する(SPEC G-02)。
 * 出典: https://maps.gsi.go.jp/development/demtile.html
 */

/** 無効値を表す画素値 x = 2^23 (R=128, G=0, B=0)。 */
export const DEM_INVALID = 0x800000;

/** 標高タイルの 1 画素を標高[m]にする。無効値は null。 */
export function decodeDem(r: number, g: number, b: number): number | null {
  let x = (r << 16) + (g << 8) + b;
  if (x === DEM_INVALID) return null;
  if (x > DEM_INVALID) x -= 1 << 24;
  return x * 0.01;
}

/** ImageData(256x256 の RGBA)を標高の格子にする。 */
export function decodeTile(data: Uint8ClampedArray, size = 256): (number | null)[] {
  const out = new Array<number | null>(size * size);
  for (let k = 0, p = 0; k < size * size; k++, p += 4) {
    out[k] = decodeDem(data[p], data[p + 1], data[p + 2]);
  }
  return out;
}

/** タイル座標(小数)から緯度[度]。 */
export function tileYToLat(fy: number, z: number): number {
  const n = 2 ** z;
  return (Math.atan(Math.sinh(Math.PI * (1 - (2 * fy) / n))) * 180) / Math.PI;
}

/** タイル座標(小数)から経度[度]。 */
export function tileXToLon(fx: number, z: number): number {
  const n = 2 ** z;
  return (fx / n) * 360 - 180;
}

export function lonLatToTile(lon: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const rad = (lat * Math.PI) / 180;
  const y = Math.floor(((1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2) * n);
  return [x, y];
}

export type Grid = {
  /** 幅(画素) */ w: number;
  /** 高さ(画素) */ h: number;
  /** [j*w+i] の標高。欠測は null */ z: (number | null)[];
  /** 格子の (i, j) を経緯度にする */ toLonLat: (i: number, j: number) => [number, number];
};

/**
 * marching squares による等高線。
 *
 * 各セルの 4 隅を見て、level をまたぐ辺で線形補間した点を結ぶ。
 * 曖昧な場合(対角の 2 隅だけが level を超える)は 4 隅の平均で分岐を決める。
 * 欠測を含むセルは飛ばす —— 補間しない(架空の地形を描かない)。
 *
 * 返すのは 2 点の線分の列。閉じた輪になるかどうかはテストで検算する(SPEC G-06)。
 */
export function marchingSquares(grid: Grid, level: number): [number, number][][] {
  return contours(grid, [level]).get(level) ?? [];
}

/**
 * 複数の高さを一度に引く。
 *
 * 高さごとに全セルを走査すると、標高帯の広い日本列島では走査回数が高さの本数倍になる。
 * セルごとに 4 隅の最小・最大を取り、その範囲に入る高さだけを見る。
 * 線を出す部分は marchingSquares と同じ経路(cellSegments)を通す —— 規則を二度書かない。
 */
export function contours(grid: Grid, levels: number[]): Map<number, [number, number][][]> {
  const out = new Map<number, [number, number][][]>();
  for (const l of levels) out.set(l, []);
  const sorted = [...levels].sort((a, b) => a - b);
  const { w, h, z } = grid;

  for (let j = 0; j < h - 1; j++) {
    for (let i = 0; i < w - 1; i++) {
      const z00 = z[j * w + i];
      const z10 = z[j * w + i + 1];
      const z11 = z[(j + 1) * w + i + 1];
      const z01 = z[(j + 1) * w + i];
      if (z00 === null || z10 === null || z11 === null || z01 === null) continue;
      const lo = Math.min(z00, z10, z11, z01);
      const hi = Math.max(z00, z10, z11, z01);
      for (const level of sorted) {
        if (level < lo) continue;
        if (level > hi) break;
        cellSegments(grid, i, j, z00, z10, z11, z01, level, out.get(level)!);
      }
    }
  }
  return out;
}

/** セル 1 個分の線分を求めて acc に足す。marchingSquares と contours の共有経路。 */
function cellSegments(
  grid: Grid, i: number, j: number,
  z00: number, z10: number, z11: number, z01: number,
  level: number, acc: [number, number][][],
): void {
  // level ちょうどの頂点は「上」に倒す(辺が二重に出るのを防ぐ)
  const b00 = z00 >= level ? 1 : 0;
  const b10 = z10 >= level ? 1 : 0;
  const b11 = z11 >= level ? 1 : 0;
  const b01 = z01 >= level ? 1 : 0;
  let idx = (b00 << 3) | (b10 << 2) | (b11 << 1) | b01;
  if (idx === 0 || idx === 15) return;

  const ix = (za: number, zb: number, ia: number, ja: number, ib: number, jb: number): [number, number] => {
    const t = (level - za) / (zb - za);
    return [ia + (ib - ia) * t, ja + (jb - ja) * t];
  };
  const top = () => ix(z00, z10, i, j, i + 1, j);
  const right = () => ix(z10, z11, i + 1, j, i + 1, j + 1);
  const bottom = () => ix(z01, z11, i, j + 1, i + 1, j + 1);
  const left = () => ix(z00, z01, i, j, i, j + 1);

  // 鞍点の分岐。中央の値が level 以上なら「高い側がつながる」向きに取る
  if (idx === 5 || idx === 10) {
    const high = (z00 + z10 + z11 + z01) / 4 >= level;
    if (idx === 5) idx = high ? 5 : 105;
    else idx = high ? 106 : 10;
  }

  const push = (a: [number, number], b: [number, number]) => {
    acc.push([grid.toLonLat(a[0], a[1]), grid.toLonLat(b[0], b[1])]);
  };

  switch (idx) {
    case 1: case 14: push(left(), bottom()); break;
    case 2: case 13: push(bottom(), right()); break;
    case 3: case 12: push(left(), right()); break;
    case 4: case 11: push(top(), right()); break;
    case 6: case 9: push(top(), bottom()); break;
    case 7: case 8: push(left(), top()); break;
    case 5:   push(left(), top()); push(bottom(), right()); break;
    case 105: push(left(), bottom()); push(top(), right()); break;
    case 10:  push(left(), bottom()); push(top(), right()); break;
    case 106: push(left(), top()); push(bottom(), right()); break;
  }
}

/** 格子の標高範囲に入る等高線の値を列挙する。 */
export function levelsFor(grid: Grid, interval: number): number[] {
  let lo = Infinity, hi = -Infinity;
  for (const v of grid.z) {
    if (v === null) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo) || !isFinite(hi)) return [];
  const out: number[] = [];
  const start = Math.ceil(lo / interval) * interval;
  for (let v = start; v <= hi; v += interval) out.push(Math.round(v * 1000) / 1000);
  return out;
}
