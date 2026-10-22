"""Integer reference, independent of candidate RTL and synthesis reports."""
from pathlib import Path


def pixel(window, mode=0):
    if len(window) != 9 or any(type(x) is not int or not 0 <= x <= 255 for x in window):
        raise ValueError("Expected nine unsigned 8-bit integers")
    a, b, c, d, e, f, g, h, i = window
    if mode == 0:
        gx = c - a + 2 * (f - d) + i - g
        gy = a - g + 2 * (b - h) + c - i
        return 255 if abs(gx) + abs(gy) > 160 else 0
    if mode == 1:
        return (a + 2*b + c + 2*d + 4*e + 2*f + g + 2*h + i) >> 4
    if mode == 2:
        return max(0, min(255, 5*e - b - d - f - h))
    if mode == 3:
        return 0
    raise ValueError("mode must be 0..3")


def gray_image(path, size=None):
    from PIL import Image
    image = Image.open(path).convert("RGB")
    if size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    w, h = image.size
    flat = [(77*r + 150*g + 29*b + 128) >> 8 for r, g, b in image.getdata()]
    return [[flat[y*w+x] for x in range(w)] for y in range(h)]


def windows(image):
    if not image or not image[0] or any(len(row) != len(image[0]) for row in image):
        raise ValueError("Nonempty rectangular image required")
    h, w = len(image), len(image[0])
    for y in range(h):
        for x in range(w):
            yield [image[max(0, min(h-1, y+dy))][max(0, min(w-1, x+dx))]
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def write_gray(path, values, width, height):
    from PIL import Image
    if len(values) != width*height:
        raise ValueError("Wrong output pixel count")
    out = Image.new("L", (width, height))
    out.putdata(values)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.save(path)

