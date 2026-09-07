"""標高タイルの二実装照合フィクスチャを作る(SPEC G-02)。

キャッシュ済みの実タイルを Python 側で全画素デコードし、言語に依らない
正規化(標高を 1/100 m 単位の整数にする = 元の 24 bit 値そのもの)で
SHA-256 を取る。TypeScript 側が同じ値を出せば、両実装は全画素で一致している。
"""
from __future__ import annotations

import base64
import hashlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from etl.common import RAW, REPO, decode_dem_rgb, write_json

OUT = REPO / "tests-js" / "fixtures" / "dem_tiles.json"
N_TILES = 8


def canonical(values: list[float | None]) -> str:
    return "\n".join("null" if v is None else str(round(v * 100)) for v in values)


def main() -> None:
    tiles = sorted((RAW / "gsi" / "dem_png").rglob("*.png"))
    if len(tiles) < N_TILES:
        raise SystemExit(f"キャッシュ済みタイルが {len(tiles)} 枚しかない({N_TILES} 枚必要)")
    # 端に寄らないよう等間隔に選ぶ
    picked = [tiles[i * len(tiles) // N_TILES] for i in range(N_TILES)]

    out = []
    for p in picked:
        raw = p.read_bytes()
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        px = im.load()
        vals = [decode_dem_rgb(*px[i, j]) for j in range(256) for i in range(256)]
        ok = [v for v in vals if v is not None]
        z, x, y = p.parts[-3], p.parts[-2], p.stem
        out.append({
            "path": f"{z}/{x}/{y}",
            "png_base64": base64.b64encode(raw).decode("ascii"),
            "pixels": len(vals),
            "valid": len(ok),
            "min_m": min(ok) if ok else None,
            "max_m": max(ok) if ok else None,
            "sha256": hashlib.sha256(canonical(vals).encode("utf-8")).hexdigest(),
        })

    write_json(OUT, {
        "note": ("国土地理院 標高タイル(dem_png)の実タイル。"
                 "sha256 は「null か、標高を 1/100 m 単位に丸めた整数」を改行で連ねた文字列に対するもの。"),
        "source": "国土地理院 標高タイル",
        "source_url": "https://maps.gsi.go.jp/development/demtile.html",
        "download_date": "2026-09-07",
        "generator": "etl/make_dem_fixture.py",
        "tiles": out,
    }, indent=1)
    total = sum(t["pixels"] for t in out)
    print(f"{OUT}: {len(out)} タイル / 全 {total} 画素")


if __name__ == "__main__":
    main()
