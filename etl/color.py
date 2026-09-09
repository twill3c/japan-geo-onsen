"""色の見分けやすさを測る(HC-257)。

凡例で意味を分けている色 —— 温泉(国土数値情報)・温泉(Wikidata)・入浴施設・火山 ——
は、**色覚型を変えても見分けられなければ、層を分けた意味が消える**。
溢れや重なりの検査ではこの故障は捕まらない。

## 計器そのものを疑う

最初、Hunt-Pointer-Estevez の LMS 行列に Viénot 1999 の係数を当てて測り、
**白が白のまま残らない**計器で偽の欠陥を出しかけた(protan で L' が負になり、
クリップされて水色になる)。色覚シミュレータは、壊れていても「それらしい色」を返すので
絵として成立してしまう。だから使う前に錨で検算する —— `anchors_ok()` がそれである。

- 無彩色(白・灰・黒)は、どの色覚型でも動かない
- 赤と緑の差は、2 型で大きく縮む

出典:
- Viénot, Brettel & Mollon (1999) "Digital video colourmaps for checking the
  legibility of displays by dichromats"
- CIEDE2000 色差式
"""
from __future__ import annotations

import math

# Viénot 1999 が用いる線形 sRGB → LMS と、その逆行列
_M = [
    [17.8824, 43.5161, 4.11935],
    [3.45565, 27.1554, 3.86714],
    [0.0299566, 0.184309, 1.46709],
]
_MINV = [
    [0.0809444479, -0.130504409, 0.116721066],
    [-0.0102485335, 0.0540193266, -0.113614708],
    [-0.000365296938, -0.00412161469, 0.693511405],
]

VISION_TYPES = ("normal", "protan", "deutan")


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"色の書き方が違う: {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _mul(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def simulate(rgb, kind: str):
    """色覚型 kind で見たときの色(0-255)。normal はそのまま返す。"""
    if kind == "normal":
        return tuple(rgb)
    lin = [_srgb_to_linear(c) for c in rgb]
    L, M, S = _mul(_M, lin)
    if kind == "protan":
        L = 2.02344 * M - 2.52581 * S
    elif kind == "deutan":
        M = 0.494207 * L + 1.24827 * S
    else:
        raise ValueError(f"知らない色覚型: {kind}")
    return tuple(_linear_to_srgb(c) * 255 for c in _mul(_MINV, (L, M, S)))


def _lab(rgb):
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e2000(c1, c2) -> float:
    """CIEDE2000 の色差。"""
    L1, a1, b1 = _lab(c1)
    L2, a2, b2 = _lab(c2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7))) if Cb > 0 else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    dhp = 0.0 if C1p * C2p == 0 else ((h2p - h1p + 180) % 360) - 180
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30))
         + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6))
         - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dth = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) if Cbp > 0 else 0.0
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dth)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                     + Rt * (dCp / Sc) * (dHp / Sh))


def distance(hex_a: str, hex_b: str, kind: str) -> float:
    """色覚型 kind で見たときの 2 色の色差。"""
    a, b = hex_to_rgb(hex_a), hex_to_rgb(hex_b)
    return delta_e2000(simulate(a, kind), simulate(b, kind))


def min_distance(colors: dict[str, str]) -> tuple[float, str, str, str]:
    """全組み合わせ × 全色覚型での最小色差と、その組。"""
    names = list(colors)
    best = (math.inf, "", "", "")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            for kind in VISION_TYPES:
                d = distance(colors[names[i]], colors[names[j]], kind)
                if d < best[0]:
                    best = (d, names[i], names[j], kind)
    return best


def anchors_ok() -> list[str]:
    """計器そのものの検算。壊れている点を文字列で返す(空なら健全)。"""
    bad = []
    for name, hexv in (("白", "#ffffff"), ("灰", "#808080"), ("黒", "#000000")):
        for kind in ("protan", "deutan"):
            d = delta_e2000(hex_to_rgb(hexv), simulate(hex_to_rgb(hexv), kind))
            if d > 1.0:
                bad.append(f"{name} が {kind} で動く(ΔE00 {d:.2f})")
    normal = distance("#ff0000", "#00ff00", "normal")
    deutan = distance("#ff0000", "#00ff00", "deutan")
    if not (deutan < normal * 0.5):
        bad.append(f"赤×緑が 2 型で縮まない(通常 {normal:.1f} → 2型 {deutan:.1f})")
    return bad
