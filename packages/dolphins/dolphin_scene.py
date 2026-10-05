"""The Dolphins addon's own picture for the channel list: a pod of bottlenose dolphins, one leaping out over the horizon, three
swimming below - drawn in code (smooth spline outlines, countershading, light shafts), so there is no image file to ship.  Needs Pillow."""
import math
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# a bottlenose dolphin seen from the side, facing right, in a 100 x 40 box (y down).  Smooth outlines: Catmull-Rom splines through these.
BODY = [(1, 19.4), (7, 17.8), (17, 14.2), (29, 10.0), (41, 6.6), (53, 4.8), (64, 5.0), (72, 6.6), (78, 8.0), (82.5, 9.0), (86.5, 10.6),
        (89.2, 13.4), (90.8, 15.6), (95, 16.1), (99, 16.8), (100.5, 17.9), (99, 19.1), (94, 19.8), (89.5, 20.8), (84.5, 23.4),
        (76, 27.0), (66, 29.6), (54, 30.6), (42, 29.6), (30, 26.6), (19, 23.4), (9, 21.6), (3, 21.0)]
FIN = [(40, 7.6), (42, 2.4), (41.2, -3.4), (38.4, -9.2), (43.2, -7.4), (49, -2.0), (55, 3.4), (61, 6.0)]
FLIPPER = [(63, 27.5), (61.5, 31.5), (58.5, 36.5), (56.4, 38.6), (61, 35.8), (66.2, 31.4), (70, 28.2)]
FLUKES = [(4, 18.9), (-2, 17.6), (-8, 15.4), (-13, 13.8), (-15.4, 14.2), (-12.4, 17.0), (-8.2, 19.6), (-12.4, 22.6),
          (-15.6, 25.2), (-13.2, 26.0), (-8, 24.4), (-2, 22.4), (4, 21.2)]
EYE, MOUTH = (82.4, 15.0), [(90.4, 18.6), (87.0, 18.9), (84.2, 18.1)]
SS = 4                                                       # drawn this much bigger, then scaled down: smooth edges


def spline(pts, closed=True, steps=10):
    """Catmull-Rom curve through the points."""
    n, out = len(pts), []
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0, p1, p2, p3 = (pts[(i + k) % n] if closed else pts[max(0, min(n - 1, i + k))] for k in (-1, 0, 1, 2))
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    if not closed: out.append(pts[-1])
    return out


def _lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def dolphin_image(length):
    """An RGBA picture of one dolphin, `length` pixels from tail to beak."""
    k = length * SS / 116                                    # the shape spans x -15..101, y -8..38
    W, H = int(118 * k), int(52 * k)
    to = lambda pts: [((x + 16) * k, (y + 9) * k) for x, y in pts]
    mask = Image.new("L", (W, H), 0)
    m = ImageDraw.Draw(mask)
    for part in (FLUKES, FIN, FLIPPER, BODY): m.polygon(to(spline(part)), fill=255)
    # countershading: dark back -> grey flank -> pale belly, plus a soft light on the upper flank
    back, flank, belly = (62, 78, 94), (128, 144, 160), (232, 236, 240)
    grad = Image.new("RGB", (W, H))
    g = ImageDraw.Draw(grad)
    for y in range(H):
        yy = y / k - 9
        if yy < 13: c = _lerp(back, flank, max(0, (yy + 8) / 21))
        elif yy < 19: c = _lerp(flank, (156, 170, 183), (yy - 13) / 6)
        else: c = _lerp((156, 170, 183), belly, min(1, (yy - 19) / 9))
        g.line([(0, y), (W, y)], fill=c)
    hi = Image.new("L", (W, H), 0)                            # highlight along the flank
    ImageDraw.Draw(hi).ellipse(to([(30, 11), (80, 19)]), fill=70)
    grad = Image.composite(Image.new("RGB", (W, H), (210, 222, 232)), grad, hi.filter(ImageFilter.GaussianBlur(6 * k)))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    inner = mask.filter(ImageFilter.MinFilter(max(3, int(0.8 * k) | 1)))                 # a soft dark rim around the whole animal
    ring = ImageChops.subtract(mask, inner).filter(ImageFilter.GaussianBlur(0.4 * k)).point(lambda v: int(v * 0.6))
    out = Image.alpha_composite(out, Image.composite(Image.new("RGBA", (W, H), (44, 56, 70, 255)), Image.new("RGBA", (W, H), (0, 0, 0, 0)), ring))
    d = ImageDraw.Draw(out)
    d.line(to(MOUTH), fill=(40, 50, 60, 220), width=max(1, int(0.7 * k)))
    ex, ey = to([EYE])[0]
    r = 1.3 * k
    d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=(20, 26, 32, 255))
    d.ellipse((ex - r * 0.2, ey - r * 0.75, ex + r * 0.35, ey - r * 0.2), fill=(240, 245, 250, 255))
    return out.resize((W // SS, H // SS), Image.LANCZOS)


def place(img, length, cx, cy, angle, alpha=1.0):
    dol = dolphin_image(length).rotate(-angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1: dol.putalpha(dol.getchannel("A").point(lambda v: int(v * alpha)))
    img.paste(dol, (int(cx - dol.width / 2), int(cy - dol.height / 2)), dol)


def scene(w=360, h=900):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    horizon = int(h * 0.42)
    for y in range(h):                                        # sky -> horizon haze -> sea, darker with depth
        if y < horizon: c = _lerp((120, 182, 236), (222, 238, 248), y / horizon)
        else: c = _lerp((46, 146, 196), (10, 58, 104), (y - horizon) / (h - horizon))
        d.line([(0, y), (w, y)], fill=c)
    sun = Image.new("L", (w, h), 0)
    ImageDraw.Draw(sun).ellipse((w * 0.64, h * 0.05, w * 0.64 + w * 0.22, h * 0.05 + w * 0.22), fill=255)
    img = Image.composite(Image.new("RGB", (w, h), (255, 244, 205)), img, sun.filter(ImageFilter.GaussianBlur(3)))
    rays = Image.new("L", (w, h), 0)                          # light shafts under water
    r = ImageDraw.Draw(rays)
    for i, x in enumerate((0.15, 0.4, 0.62, 0.85)):
        r.polygon([(w * x - 8, horizon), (w * x + 8, horizon), (w * x + 60 - i * 25, h), (w * x - 30 - i * 10, h)], fill=38)
    img = Image.composite(Image.new("RGB", (w, h), (170, 220, 240)), img, rays.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    for i in range(10):                                      # ripples near the surface, fading with depth
        y = horizon + 3 + i * i * 2.2
        amp = 1.5 + i * 0.4
        d.line([(x, y + amp * math.sin(x / (18 + i * 4) * math.pi + i)) for x in range(0, w + 6, 4)], fill=_lerp((150, 215, 240), (46, 120, 170), i / 10), width=1)
    place(img, w * 0.78, w * 0.46, horizon - w * 0.12, -30)                       # leaping out over the horizon
    d = ImageDraw.Draw(img)
    for i in range(7):                                       # splash where it left the water
        sx = w * 0.18 + i * 7
        d.ellipse((sx - 3, horizon - 6 - (i % 3) * 5, sx + 3, horizon - (i % 3) * 5), fill=(235, 248, 255))
    place(img, w * 0.84, w * 0.54, horizon + (h - horizon) * 0.30, 4, 0.95)
    place(img, w * 0.74, w * 0.40, horizon + (h - horizon) * 0.60, -7, 0.85)
    place(img, w * 0.62, w * 0.62, horizon + (h - horizon) * 0.86, 8, 0.72)       # further away: fainter
    d = ImageDraw.Draw(img)
    for i in range(26):                                      # bubbles
        bx, by = (i * 97) % w, horizon + 20 + (i * 53) % int(h - horizon - 20)
        rr = 1.5 + i % 3
        d.ellipse((bx - rr, by - rr, bx + rr, by + rr), outline=(200, 235, 250))
    return img
