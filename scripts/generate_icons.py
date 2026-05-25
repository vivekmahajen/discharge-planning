"""Generate PWA icon PNGs for all required sizes."""
import struct
import zlib
import os

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

# Brand colours
BG = (0, 82, 155)       # #00529B — deep blue
FG = (255, 255, 255)    # white cross / H


def _png_chunk(name: bytes, data: bytes) -> bytes:
    c = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)


def _write_png(path: str, pixels: list[list[tuple]]) -> None:
    h = len(pixels)
    w = len(pixels[0])
    raw = b""
    for row in pixels:
        raw += b"\x00"
        for r, g, b in row:
            raw += bytes([r, g, b])
    compressed = zlib.compress(raw, 9)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(_png_chunk(b"IDAT", compressed))
        f.write(_png_chunk(b"IEND", b""))


def _make_icon(size: int) -> list[list[tuple]]:
    pixels = [[BG] * size for _ in range(size)]
    pad = size // 6
    thick = max(size // 12, 2)
    cx = size // 2
    cy = size // 2
    arm = size // 2 - pad
    # Vertical bar
    for y in range(cy - arm, cy + arm + 1):
        for x in range(cx - thick, cx + thick + 1):
            if 0 <= y < size and 0 <= x < size:
                pixels[y][x] = FG
    # Horizontal bar
    for x in range(cx - arm, cx + arm + 1):
        for y in range(cy - thick, cy + thick + 1):
            if 0 <= y < size and 0 <= x < size:
                pixels[y][x] = FG
    return pixels


def main() -> None:
    out = os.path.join(os.path.dirname(__file__), "..", "static", "icons")
    os.makedirs(out, exist_ok=True)
    for size in SIZES:
        path = os.path.join(out, f"icon-{size}x{size}.png")
        _write_png(path, _make_icon(size))
        print(f"  {path}")
    # Apple touch icon (180x180)
    path_180 = os.path.join(out, "apple-touch-icon.png")
    _write_png(path_180, _make_icon(180))
    print(f"  {path_180}")
    # Shortcut icons: simple coloured squares
    shortcuts = [
        ("shortcut-new-plan.png", (0, 128, 96)),
        ("shortcut-my-patients.png", (0, 82, 155)),
        ("shortcut-ward-barriers.png", (180, 60, 0)),
    ]
    for fname, bg in shortcuts:
        pixels = [[bg] * 96 for _ in range(96)]
        _write_png(os.path.join(out, fname), pixels)
        print(f"  {os.path.join(out, fname)}")


if __name__ == "__main__":
    main()
