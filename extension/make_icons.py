"""生成插件图标（16/32/48/128 PNG）：蓝色圆角方块 + 白色靶心。只依赖标准库。

用法：python extension/make_icons.py
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "icons"
C1 = C2 = (51, 112, 255)   # #3370ff，纯色，与网页主色一致


def pixel(x: float, y: float) -> tuple[int, int, int, int]:
    """x、y 为 0..1 的坐标，返回 RGBA。"""
    r = 0.22   # 圆角半径
    dx, dy = max(r - x, 0, x - (1 - r)), max(r - y, 0, y - (1 - r))
    if math.hypot(dx, dy) > r:
        return 0, 0, 0, 0
    t = (x + y) / 2
    base = tuple(round(a + (b - a) * t) for a, b in zip(C1, C2))
    d = math.hypot(x - 0.5, y - 0.5)
    white = 0.30 < d < 0.38 or 0.15 < d < 0.22 or d < 0.07
    return (255, 255, 255, 255) if white else (*base, 255)


def render(size: int, ss: int = 4) -> bytes:
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    p = pixel((px + (sx + 0.5) / ss) / size, (py + (sy + 0.5) / ss) / size)
                    a = p[3]
                    acc[0] += p[0] * a; acc[1] += p[1] * a; acc[2] += p[2] * a; acc[3] += a
            n = ss * ss
            alpha = acc[3] / n
            rgb = [round(acc[i] / acc[3]) if acc[3] else 0 for i in range(3)]
            row += bytes([*rgb, round(alpha)])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for s in (16, 32, 48, 128):
        (OUT / f"icon{s}.png").write_bytes(render(s))
        print("icons/icon%d.png" % s)
