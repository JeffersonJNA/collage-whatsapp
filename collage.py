"""Motor de collage (Pillow puro, sin Streamlit).

Cada plantilla es una lista de rectangulos normalizados (x, y, ancho, alto)
dentro del area de fotos. Asi la misma plantilla funciona en 1:1, 4:5, 9:16, etc.

Los fondos pueden ser:

* un color solido,
* un preset decorativo (degradado, bokeh, confeti...), o
* una imagen del usuario (con desenfoque y tono ajustables).
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

Rect = tuple[float, float, float, float]

# --------------------------------------------------------------------------- #
# Plantillas
# --------------------------------------------------------------------------- #

LAYOUTS: dict[str, list[Rect]] = {
    "1 foto · póster": [
        (0.0, 0.0, 1.0, 1.0),
    ],
    "2 fotos · lado a lado": [
        (0.0, 0.0, 0.5, 1.0),
        (0.5, 0.0, 0.5, 1.0),
    ],
    "3 fotos · 1 grande + 2": [
        (0.0, 0.0, 0.60, 1.0),
        (0.60, 0.0, 0.40, 0.5),
        (0.60, 0.5, 0.40, 0.5),
    ],
    "3 fotos · tira vertical": [
        (0.0, 0.0, 1.0, 1 / 3),
        (0.0, 1 / 3, 1.0, 1 / 3),
        (0.0, 2 / 3, 1.0, 1 / 3),
    ],
    "4 fotos · cuadrícula": [
        (0.0, 0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ],
    "5 fotos · 1 + 4": [
        (0.0, 0.0, 1.0, 0.55),
        (0.00, 0.55, 0.25, 0.45),
        (0.25, 0.55, 0.25, 0.45),
        (0.50, 0.55, 0.25, 0.45),
        (0.75, 0.55, 0.25, 0.45),
    ],
    "6 fotos · 3×2": [
        (0.0, 0.0, 1 / 3, 0.5),
        (1 / 3, 0.0, 1 / 3, 0.5),
        (2 / 3, 0.0, 1 / 3, 0.5),
        (0.0, 0.5, 1 / 3, 0.5),
        (1 / 3, 0.5, 1 / 3, 0.5),
        (2 / 3, 0.5, 1 / 3, 0.5),
    ],
    "9 fotos · 3×3": [
        (c / 3, r / 3, 1 / 3, 1 / 3) for r in range(3) for c in range(3)
    ],
    # Filas de fotos: cada fila puede tener una pareja (2 fotos lado a lado).
    "6 fotos · 3 parejas": [
        rect
        for r in range(3)
        for rect in (
            (0.0, r / 3, 0.5, 1 / 3),
            (0.5, r / 3, 0.5, 1 / 3),
        )
    ],
    # Fotos apiladas verticalmente (ideal para formatos verticales tipo stories).
    "2 fotos · vertical": [
        (0.0, 0.0, 1.0, 0.5),
        (0.0, 0.5, 1.0, 0.5),
    ],
}

ASPECTS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1600, 900),
    # Formatos nuevos añadidos en esta iteración.
    "2:3": (1080, 1620),
    "16:10": (1440, 900),
}

PLACEHOLDER_BG = "#E8EDF3"
PLACEHOLDER_FG = "#9AA6B6"

FONT_FAMILIES: dict[str, tuple[str, ...]] = {
    "bold": (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
    "hand": (
        "C:/Windows/Fonts/segoescr.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ),
    "serif": (
        "C:/Windows/Fonts/georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    ),
    "mono": (
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ),
}

FONT_LABELS: dict[str, str] = {
    "bold": "Negrita",
    "hand": "Manuscrita",
    "serif": "Serif",
    "mono": "Mono",
}

# --------------------------------------------------------------------------- #
# Fondos prediseñados
# --------------------------------------------------------------------------- #

PRESETS: dict[str, dict] = {
    "blanco": {"label": "Blanco", "kind": "solid", "colors": ["#FFFFFF"]},
    "crema": {"label": "Crema", "kind": "solid", "colors": ["#FBF5EB"]},
    "noche": {
        "label": "Noche",
        "kind": "gradient",
        "colors": ["#2B3039", "#0D0E12"],
        "angle": 118,
        "glow": 0.05,
    },
    "verde": {
        "label": "Verde",
        "kind": "gradient",
        "colors": ["#F2FDF8", "#C6F0DA", "#96E0C0"],
        "angle": 130,
    },
    "atardecer": {
        "label": "Atardecer",
        "kind": "gradient",
        "colors": ["#FFE9C9", "#FFB79E", "#E8869B"],
        "angle": 120,
        "glow": 0.06,
    },
    "oceano": {
        "label": "Océano",
        "kind": "gradient",
        "colors": ["#E6F9FF", "#A8DCEE", "#6FA6C9"],
        "angle": 135,
    },
    "lavanda": {
        "label": "Lavanda",
        "kind": "gradient",
        "colors": ["#F8EEFF", "#DDC6F8", "#B69CE8"],
        "angle": 128,
        "glow": 0.05,
    },
    "menta": {
        "label": "Menta",
        "kind": "gradient",
        "colors": ["#EBFFF8", "#BDF2E0", "#82D9BC"],
        "angle": 132,
    },
    "bokeh": {
        "label": "Bokeh",
        "kind": "bokeh",
        "colors": ["#2E2647", "#151120"],
        "angle": 110,
    },
    "confeti": {
        "label": "Confeti",
        "kind": "confetti",
        "colors": ["#FFFDF8"],
    },
    "madera": {
        "label": "Madera",
        "kind": "wood",
        "colors": ["#C9A57A", "#8B6A45", "#5E4530"],
    },
    "marmol": {
        "label": "Mármol",
        "kind": "marble",
        "colors": ["#F4F1EC", "#D9D3CB", "#A8A096"],
    },
    "lino": {
        "label": "Lino",
        "kind": "linen",
        "colors": ["#F1ECE2", "#D8D0C2"],
    },
    "papel": {
        "label": "Papel",
        "kind": "paper",
        "colors": ["#FBF8F2", "#ECE6DB"],
    },
    "aurora": {
        "label": "Aurora",
        "kind": "mesh",
        "colors": ["#A8E6CF", "#FFD3B6", "#FF8B94", "#C7CEEA", "#B5EAD7"],
    },
    # Nuevos fondos añadidos en esta iteración.
    "sol": {
        "label": "Sol",
        "kind": "gradient",
        "colors": ["#FFF3C4", "#FFD66B", "#FFB347"],
        "angle": 115,
    },
    "marino": {
        "label": "Marino",
        "kind": "gradient",
        "colors": ["#0B1B33", "#14395C", "#1E4E7E"],
        "angle": 140,
    },
}

CONFETTI_COLORS = (
    "#FFC9DE",
    "#A5D8FF",
    "#B2F2BB",
    "#FFEC99",
    "#D0BFFF",
    "#FFD8A8",
    "#96F2D7",
    "#FFA8A8",
)

THUMB_PALETTE: tuple[tuple[str, str], ...] = (
    ("#FFE3C7", "#FFB47A"),
    ("#CDE8FF", "#7FB8E8"),
    ("#C8F5DF", "#78D6AB"),
    ("#FFD6E6", "#F59BBD"),
    ("#DFD3FF", "#AF97EC"),
    ("#FFF1C2", "#EFC866"),
    ("#CDF3F5", "#79D2D9"),
    ("#FFD9D2", "#EF9C8D"),
    ("#DDE7F5", "#9DB4D0"),
)


@dataclass(frozen=True)
class Style:
    """Ajustes visuales del collage."""

    margin: int = 48
    gap: int = 18
    radius: int = 30
    background: str = "#FFFFFF"
    caption: str = ""
    font: str = "bold"
    background_preset: str | None = None
    background_image: Image.Image | None = None
    background_blur: float = 0.0
    background_dim: float = 0.0


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=256)
def _font(size: int, family: str = "bold") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_FAMILIES.get(family, FONT_FAMILIES["bold"]):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


@lru_cache(maxsize=256)
def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _rgb(color: str) -> tuple[int, int, int]:
    return ImageColor.getrgb(color)[:3]


def _mix(stops: list[tuple[int, int, int]], t: float) -> tuple[int, int, int]:
    """Interpola una lista de colores en t (0..1)."""
    if t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    pos = t * (len(stops) - 1)
    index = min(int(pos), len(stops) - 2)
    frac = pos - index
    a, b = stops[index], stops[index + 1]
    return (
        round(a[0] + (b[0] - a[0]) * frac),
        round(a[1] + (b[1] - a[1]) * frac),
        round(a[2] + (b[2] - a[2]) * frac),
    )


def _gradient(
    size: tuple[int, int],
    colors: list[str],
    angle: float = 135.0,
    glow: float = 0.0,
) -> Image.Image:
    """Degradado diagonal suave a partir de 2+ colores.

    Se pinta en pequeño (rapido y sin banding visible) y se escala.
    """
    width, height = size
    sw = 80
    sh = max(24, round(sw * height / width))
    stops = [_rgb(c) for c in colors]

    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    corners = ((0, 0), (sw - 1, 0), (0, sh - 1), (sw - 1, sh - 1))
    projections = [x * dx + y * dy for x, y in corners]
    pmin = min(projections)
    span = (max(projections) - pmin) or 1.0

    gx, gy = sw * 0.26, sh * 0.16
    gr = 0.9 * max(sw, sh)

    pixels: list[tuple[int, int, int]] = []
    for y in range(sh):
        for x in range(sw):
            t = ((x * dx + y * dy) - pmin) / span
            r, g, b = _mix(stops, t)
            if glow:
                dist = math.hypot(x - gx, y - gy) / gr
                light = glow * max(0.0, 1.0 - dist) ** 2
                r = min(255, round(r + 255 * light))
                g = min(255, round(g + 255 * light))
                b = min(255, round(b + 255 * light))
            pixels.append((r, g, b))

    small = Image.new("RGB", (sw, sh))
    small.putdata(pixels)
    return small.resize((width, height), Image.BICUBIC)


def _bokeh(size: tuple[int, int], colors: list[str], angle: float) -> Image.Image:
    """Fondo oscuro con luces desenfocadas."""
    base = _gradient(size, colors, angle=angle, glow=0.03)
    width, height = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(11)
    palette = (
        (255, 255, 255),
        (255, 219, 186),
        (176, 232, 255),
        (255, 196, 224),
        (196, 255, 221),
    )
    for _ in range(26):
        radius = rng.uniform(0.02, 0.10) * width
        cx = rng.uniform(-0.05, 1.05) * width
        cy = rng.uniform(-0.05, 1.05) * height
        color = rng.choice(palette)
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=color + (rng.randint(30, 78),),
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(2, width * 0.012)))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _confetti(size: tuple[int, int], colors: list[str]) -> Image.Image:
    """Fondo claro con confeti pastel."""
    base = Image.new("RGB", size, _rgb(colors[0]))
    width, height = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(5)
    total = max(30, int(width * height / 4200))
    for _ in range(total):
        w = rng.uniform(0.010, 0.026) * width
        h = w * rng.uniform(0.55, 1.5)
        x = rng.uniform(-0.01, 1.0) * width
        y = rng.uniform(-0.01, 1.0) * height
        color = _rgb(rng.choice(CONFETTI_COLORS))
        draw.rounded_rectangle(
            (x, y, x + w, y + h),
            radius=w * 0.35,
            fill=color + (rng.randint(130, 205),),
        )
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _wood(size: tuple[int, int], colors: list[str]) -> Image.Image:
    """Madera cálida con veta vertical sutil."""
    width, height = size
    base = _gradient(size, colors, angle=90, glow=0.0)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(7)
    stops = [_rgb(c) for c in colors]
    for _ in range(max(18, width // 28)):
        x = rng.uniform(0, width)
        w = rng.uniform(0.6, 2.4)
        shade = rng.choice(stops)
        alpha = rng.randint(18, 55)
        draw.line((x, 0, x + rng.uniform(-width * 0.02, width * 0.02), height), fill=shade + (alpha,), width=max(1, round(w)))
    # Nudos ocasionales
    for _ in range(3):
        cx = rng.uniform(0.1, 0.9) * width
        cy = rng.uniform(0.1, 0.9) * height
        r = rng.uniform(0.012, 0.026) * width
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(60, 40, 25, 90))
    overlay = overlay.filter(ImageFilter.GaussianBlur(1.2))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _marble(size: tuple[int, int], colors: list[str]) -> Image.Image:
    """Mármol blanco/gris con vetas suaves."""
    width, height = size
    base = Image.new("RGB", size, _rgb(colors[0]))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(13)
    stops = [_rgb(c) for c in colors[1:]] or [_rgb(colors[0])]
    for _ in range(max(6, width // 90)):
        pts = []
        x = rng.uniform(0, width)
        y = rng.uniform(0, height)
        for _ in range(rng.randint(6, 12)):
            x += rng.uniform(-width * 0.12, width * 0.12)
            y += rng.uniform(-height * 0.08, height * 0.08)
            pts.append((x, y))
        color = rng.choice(stops) + (rng.randint(40, 95),)
        draw.line(pts, fill=color, width=rng.randint(1, 3), joint="curve")
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(2, width * 0.006)))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _linen(size: tuple[int, int], colors: list[str]) -> Image.Image:
    """Tejido lino con trama cruzada."""
    width, height = size
    base = _gradient(size, colors, angle=135, glow=0.0)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    step = max(6, width // 120)
    for i in range(0, width, step):
        draw.line((i, 0, i, height), fill=(0, 0, 0, 14), width=1)
    for j in range(0, height, step):
        draw.line((0, j, width, j), fill=(255, 255, 255, 12), width=1)
    rng = random.Random(9)
    for _ in range(max(40, width * height // 3000)):
        x = rng.randrange(0, width, step)
        y = rng.randrange(0, height, step)
        if rng.random() < 0.5:
            draw.point((x, y), fill=(0, 0, 0, 30))
        else:
            draw.point((x, y), fill=(255, 255, 255, 24))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _paper(size: tuple[int, int], colors: list[str]) -> Image.Image:
    """Papel con grano muy sutil."""
    width, height = size
    base = Image.new("RGB", size, _rgb(colors[0]))
    rng = random.Random(21)
    pixels = list(base.getdata())
    out = []
    for (r, g, b) in pixels:
        n = rng.randint(-6, 6)
        out.append((max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n))))
    img = Image.new("RGB", size)
    img.putdata(out)
    # Vignette ligera
    overlay = Image.new("L", size, 0)
    od = ImageDraw.Draw(overlay)
    od.ellipse((-width * 0.15, -height * 0.15, width * 1.15, height * 1.15), fill=255)
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(8, width * 0.08)))
    vignette = Image.new("RGB", size, (0, 0, 0))
    img = Image.composite(img, vignette, overlay.point(lambda v: 255 - v // 4))
    return img


def _mesh(size: tuple[int, int], colors: list[str]) -> Image.Image:
    """Degradado mesh (aurora): varias manchas de color desenfocadas."""
    width, height = size
    base = Image.new("RGB", size, _rgb(colors[0]))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(31)
    palette = [_rgb(c) for c in colors]
    for _ in range(7):
        color = rng.choice(palette)
        rx = rng.uniform(0.15, 0.55) * width
        ry = rng.uniform(0.15, 0.55) * height
        cx = rng.uniform(0.0, 1.0) * width
        cy = rng.uniform(0.0, 1.0) * height
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=color + (rng.randint(90, 150),))
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(12, width * 0.12)))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


@lru_cache(maxsize=64)
def _preset_cached(name: str, size: tuple[int, int]) -> Image.Image:
    spec = PRESETS[name]
    colors = spec["colors"]
    kind = spec.get("kind", "solid")
    if kind == "solid":
        return Image.new("RGB", size, _rgb(colors[0]))
    if kind == "bokeh":
        return _bokeh(size, colors, spec.get("angle", 110))
    if kind == "confetti":
        return _confetti(size, colors)
    if kind == "wood":
        return _wood(size, colors)
    if kind == "marble":
        return _marble(size, colors)
    if kind == "linen":
        return _linen(size, colors)
    if kind == "paper":
        return _paper(size, colors)
    if kind == "mesh":
        return _mesh(size, colors)
    return _gradient(size, colors, spec.get("angle", 135), spec.get("glow", 0.0))


def render_preset(name: str, size: tuple[int, int]) -> Image.Image:
    """Fondo decorativo a medida (copia, para poder pintar encima)."""
    return _preset_cached(name, tuple(size)).copy()


def build_background(size: tuple[int, int], style: Style) -> Image.Image:
    """Construye el fondo final: imagen propia > preset > color solido."""
    if style.background_image is not None:
        bg = ImageOps.fit(
            style.background_image.convert("RGB"), size, method=Image.LANCZOS
        )
        if style.background_blur > 0:
            radius = size[0] * (style.background_blur / 100) * 0.06
            if radius >= 0.6:
                bg = bg.filter(ImageFilter.GaussianBlur(radius))
        if style.background_dim:
            amount = style.background_dim / 100
            if amount > 0:
                bg = Image.blend(bg, Image.new("RGB", size, (0, 0, 0)), min(1.0, amount))
            else:
                bg = Image.blend(
                    bg, Image.new("RGB", size, (255, 255, 255)), min(1.0, -amount)
                )
        return bg
    if style.background_preset:
        return render_preset(style.background_preset, size)
    return Image.new("RGB", size, style.background)


def contrast_color(background: str) -> str:
    """Devuelve negro o blanco segun el brillo del fondo."""
    try:
        r, g, b = _rgb(background)
    except ValueError:
        return "#111827"
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111827" if luminance > 0.55 else "#FFFFFF"


def _luminance(image: Image.Image) -> float:
    small = image.convert("L").resize((32, 32), Image.BILINEAR)
    data = small.tobytes()
    return sum(data) / (255 * len(data))


def _hairline(background: str) -> str:
    """Color de borde interior que apenas se nota sobre el fondo elegido."""
    return "#E5E7EB" if contrast_color(background) == "#111827" else "#1F2937"


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(
        img.convert("RGB"), size, method=Image.LANCZOS, centering=(0.5, 0.42)
    )


def _pixel_rect(
    slot: Rect, canvas: tuple[int, int], margin: int, gap: int, extra_bottom: int
) -> tuple[int, int, int, int]:
    width, height = canvas
    inner_w = width - 2 * margin
    inner_h = height - 2 * margin - extra_bottom
    rx, ry, rw, rh = slot
    x0 = margin + rx * inner_w
    y0 = margin + ry * inner_h
    x1 = x0 + rw * inner_w
    y1 = y0 + rh * inner_h
    # Cada foto cede medio hueco por lado: los huecos quedan parejos.
    x0 += gap / 2
    y0 += gap / 2
    x1 -= gap / 2
    y1 -= gap / 2
    return round(x0), round(y0), round(x1), round(y1)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start: int,
    floor: int = 18,
    family: str = "bold",
) -> tuple[ImageFont.ImageFont, str]:
    size = start
    while size > floor:
        font = _font(size, family)
        if draw.textlength(text, font=font) <= max_width:
            return font, text
        size -= 2
    font = _font(floor, family)
    clipped = text
    while clipped and draw.textlength(clipped + "…", font=font) > max_width:
        clipped = clipped[:-1]
    return font, (clipped + "…") if clipped != text else text


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #


def render_collage(
    layout: str,
    aspect: str,
    photos: dict[int, Image.Image],
    style: Style = Style(),
) -> Image.Image:
    """Devuelve el collage RGB listo para descargar."""
    slots = LAYOUTS[layout]
    canvas_size = ASPECTS[aspect]
    width, height = canvas_size

    background = build_background(canvas_size, style)
    luminance = _luminance(background)
    dark = luminance < 0.55
    text_color = "#FFFFFF" if dark else "#111827"

    canvas = background.convert("RGB")
    caption = style.caption.strip()
    caption_h = int(height * 0.075) if caption else 0

    overlay = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    empties: list[tuple[tuple[int, int, int, int], int, int, int, int]] = []

    for index, slot in enumerate(slots):
        box = _pixel_rect(slot, canvas_size, style.margin, style.gap, caption_h)
        w = max(1, box[2] - box[0])
        h = max(1, box[3] - box[1])
        radius = max(0, min(style.radius, min(w, h) // 2))

        photo = photos.get(index)
        if photo is None:
            fill = (255, 255, 255, 120) if dark else (255, 255, 255, 205)
            edge = (255, 255, 255, 90) if dark else (17, 24, 39, 26)
            odraw.rounded_rectangle(box, radius=radius, fill=fill, outline=edge, width=1)
            empties.append((box, radius, w, h, index))
            continue

        tile = _cover(photo, (w, h))
        canvas.paste(tile, (box[0], box[1]), _rounded_mask((w, h), radius))

        # Borde interior muy sutil: separa las fotos del fondo.
        if radius > 0:
            edge = (255, 255, 255, 85) if dark else (17, 24, 39, 40)
            odraw.rounded_rectangle(box, radius=radius, outline=edge, width=2)

    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    for box, _radius, w, h, index in empties:
        number = str(index + 1)
        font = _font(max(24, min(w, h) // 5), style.font)
        tw = draw.textlength(number, font=font)
        ascent, descent = font.getmetrics()
        draw.text(
            (box[0] + (w - tw) / 2, box[1] + (h - (ascent + descent)) / 2),
            number,
            font=font,
            fill=PLACEHOLDER_FG,
        )

    if caption:
        top = height - style.margin - caption_h
        band_w = width - 2 * style.margin
        font, text = _fit_text(
            draw,
            caption,
            band_w,
            start=int(caption_h * 0.62),
            floor=18,
            family=style.font,
        )
        cx, cy = width / 2, top + caption_h / 2
        shadow = (0, 0, 0, 120)
        layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((cx + 1, cy + 2), text, font=font, fill=shadow, anchor="mm")
        ld.text((cx, cy), text, font=font, fill=text_color, anchor="mm")
        canvas = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")

    return canvas


def to_jpeg(image: Image.Image, quality: int = 88, max_side: int | None = None) -> bytes:
    """JPEG en memoria, opcionalmente reducido (para compartir rapido)."""
    img = image.convert("RGB")
    if max_side and max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def to_png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Miniaturas para los selectores visuales de la app
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=32)
def layout_thumbnail(layout: str, width: int = 340, height: int = 250) -> Image.Image:
    """Miniatura de la plantilla: huecos pastel con forma real del collage."""
    slots = LAYOUTS[layout]
    scale = 2
    canvas_size = (width * scale, height * scale)
    canvas = _gradient(canvas_size, ["#FFFFFF", "#E9F1F8"], angle=120)
    pad = int(min(canvas_size) * 0.10)
    gap = int(min(canvas_size) * 0.02)
    inner_w = canvas_size[0] - 2 * pad
    inner_h = canvas_size[1] - 2 * pad
    radius = int(min(canvas_size) * 0.035)

    for index, (rx, ry, rw, rh) in enumerate(slots):
        x0 = pad + rx * inner_w + gap / 2
        y0 = pad + ry * inner_h + gap / 2
        x1 = pad + (rx + rw) * inner_w - gap / 2
        y1 = pad + (ry + rh) * inner_h - gap / 2
        box = (round(x0), round(y0), round(max(x0 + 2, x1)), round(max(y0 + 2, y1)))
        w = box[2] - box[0]
        h = box[3] - box[1]
        light, dark = THUMB_PALETTE[index % len(THUMB_PALETTE)]
        tile = _gradient((max(8, w), max(8, h)), [light, dark], angle=140)
        canvas.paste(tile, (box[0], box[1]), _rounded_mask((w, h), radius))

    return canvas.resize((width, height), Image.LANCZOS)


@lru_cache(maxsize=64)
def preset_thumbnail(name: str, width: int = 340, height: int = 250) -> Image.Image:
    return render_preset(name, (width, height))


@lru_cache(maxsize=16)
def aspect_thumbnail(
    aspect_key: str, width: int = 340, height: int = 250
) -> Image.Image:
    """Tarjeta que muestra la proporción real del formato (ej. 9:16, 1:1)."""
    w, h = ASPECTS[aspect_key]
    scale = 2
    size = (width * scale, height * scale)
    canvas = _gradient(size, ["#FFFFFF", "#E9F1F8"], angle=120)
    draw = ImageDraw.Draw(canvas)
    # Marco representativo centrado con la proporción exacta.
    scale_f = 0.72
    box_w = int(size[0] * scale_f)
    box_h = int(round(box_w * h / w))
    x0 = (size[0] - box_w) // 2
    y0 = (size[1] - box_h) // 2
    draw.rounded_rectangle(
        (x0, y0, x0 + box_w, y0 + box_h),
        radius=int(min(size) * 0.04),
        fill="#FFFFFF",
        outline="#25D366",
        width=max(3, scale * 2),
    )
    return canvas.resize((width, height), Image.LANCZOS)


def custom_thumbnail(width: int = 340, height: int = 250) -> Image.Image:
    """Tarjeta 'Tu foto': marco punteado con un signo +."""
    scale = 2
    size = (width * scale, height * scale)
    canvas = _gradient(size, ["#F7FAFC", "#E8EEF5"], angle=120)
    draw = ImageDraw.Draw(canvas)
    inset = int(min(size) * 0.12)
    box = (inset, inset, size[0] - inset, size[1] - inset)
    radius = int(min(size) * 0.07)
    # Borde discontinuo dibujado a mano (Pillow no lo trae).
    dash, space = 14 * scale, 9 * scale
    color = (150, 165, 183)
    width_line = max(2, scale * 2)
    for (x0, y0, x1, y1) in (
        (box[0], box[1], box[2], box[1]),
        (box[2], box[1], box[2], box[3]),
        (box[2], box[3], box[0], box[3]),
        (box[0], box[3], box[0], box[1]),
    ):
        length = math.dist((x0, y0), (x1, y1))
        steps = max(1, int(length // (dash + space)))
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        for step in range(steps + 1):
            start = step * (dash + space)
            end = min(start + dash, length)
            if start >= length:
                break
            draw.line(
                (
                    x0 + ux * start,
                    y0 + uy * start,
                    x0 + ux * end,
                    y0 + uy * end,
                ),
                fill=color,
                width=width_line,
            )
    cx, cy, arm = size[0] / 2, size[1] / 2, min(size) * 0.13
    draw.rounded_rectangle(
        (cx - arm, cy - width_line * 1.6, cx + arm, cy + width_line * 1.6),
        radius=width_line,
        fill=color,
    )
    draw.rounded_rectangle(
        (cx - width_line * 1.6, cy - arm, cx + width_line * 1.6, cy + arm),
        radius=width_line,
        fill=color,
    )
    return canvas.resize((width, height), Image.LANCZOS)


def color_thumbnail(width: int = 340, height: int = 250) -> Image.Image:
    """Tarjeta 'Color': rueda de color suave."""
    scale = 2
    size = (width * scale, height * scale)
    base = Image.new("RGB", size, "#FFFFFF")
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(3)
    palette = (
        "#FF9AA2",
        "#FFB7B2",
        "#FFDAC1",
        "#E2F0CB",
        "#B5EAD7",
        "#C7CEEA",
        "#B8C0FF",
        "#E7C6FF",
    )
    radius = min(size) * 0.30
    cx, cy = size[0] * 0.5, size[1] * 0.5
    for _ in range(7):
        color = _rgb(rng.choice(palette))
        ox = rng.uniform(-0.18, 0.18) * size[0]
        oy = rng.uniform(-0.18, 0.18) * size[1]
        draw.ellipse(
            (cx + ox - radius, cy + oy - radius, cx + ox + radius, cy + oy + radius),
            fill=color + (150,),
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(size[0] * 0.02))
    merged = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    return merged.resize((width, height), Image.LANCZOS)
