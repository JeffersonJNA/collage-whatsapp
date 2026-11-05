"""Collage Express · plantillas de collage con cámara y envío por WhatsApp.

Ejecutar:  streamlit run app.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from datetime import datetime
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageOps

from collage import (
    ASPECTS,
    FONT_FAMILIES,
    FONT_LABELS,
    LAYOUTS,
    PRESETS,
    Style,
    _font,
    aspect_thumbnail,
    color_thumbnail,
    custom_thumbnail,
    layout_thumbnail,
    preset_thumbnail,
    render_collage,
    to_jpeg,
    to_png,
)

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Collage Express · WhatsApp",
    page_icon="📸",
    layout="centered",
    initial_sidebar_state="collapsed",
)

COUNTRIES = {
    "Perú (+51)": "51",
    "México (+52)": "52",
    "Colombia (+57)": "57",
    "Chile (+56)": "56",
    "Argentina (+54)": "54",
    "Ecuador (+593)": "593",
    "Bolivia (+591)": "591",
    "Venezuela (+58)": "58",
    "EE. UU. (+1)": "1",
    "España (+34)": "34",
    "Otro país (escribe el código)": "",
}

# Etiqueta corta para la tarjeta de cada plantilla.
LAYOUT_LABELS = {
    "1 foto · póster": "Póster",
    "2 fotos · lado a lado": "2 · lados",
    "3 fotos · 1 grande + 2": "3 · 1+2",
    "3 fotos · tira vertical": "3 · tira",
    "4 fotos · cuadrícula": "4 · grid",
    "5 fotos · 1 + 4": "5 · 1+4",
    "6 fotos · 3×2": "6 · 3×2",
    "6 fotos · 3 parejas": "6 · parejas",
    "9 fotos · 3×3": "9 · 3×3",
    "2 fotos · vertical": "2 · stack",
}

CSS = """
<style>
.block-container {padding-top: 1.0rem; padding-bottom: 4rem; max-width: 760px;}
h1, h2, h3, h4 {letter-spacing: -0.02em;}
[data-testid="stCameraInput"] video {border-radius: 18px;}
[data-testid="stCameraInput"] button {border-radius: 14px; font-weight: 600;}
[data-testid="stCameraInputButton"] {
  font-size: 0; background: #25D366; border: 0; color: #06281a;
  padding: 0.65rem 1rem; font-weight: 800;
}
[data-testid="stCameraInputButton"]::after {content: "📷 Tomar foto"; font-size: 1.02rem;}
.stButton > button {border-radius: 14px;}
[data-testid="stDownloadButton"] > button {border-radius: 14px; font-weight: 600;}
[data-testid="stLinkButton"] a {border-radius: 14px; font-weight: 700;}
div[data-testid="stExpander"] details {border-radius: 16px;}
/* Rejilla de tarjetas: sin márgenes sobrantes */
.st-key-thumbs [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: 6px !important;}
.st-key-thumbs [data-testid="stColumn"] {flex: 1 1 0 !important; width: 0 !important; min-width: 0 !important;}
.st-key-thumbs [data-testid="stColumn"] [data-testid="stElementContainer"] {margin-bottom: 0 !important;}
.st-key-thumbs [data-testid="stImage"] {width: 100%;}
.st-key-thumbs [data-testid="stImage"] img {
  width: 100%; max-width: 100%; height: auto; border-radius: 12px;
}
.st-key-thumbs [data-testid="stElementContainer"] {margin-bottom: 0.15rem;}
/* Botones de edicion por foto: compactos, en fila, tactiles */
.st-key-thumbs .stButton > button {
  min-width: 44px !important; height: 38px !important; padding: 0 8px !important;
  font-size: 15px !important; line-height: 1 !important; border-radius: 10px !important;
  font-weight: 700;
}
.st-key-thumbs [data-testid="stHorizontalBlock"] {gap: 4px !important;}
div[data-testid="stHorizontalBlock"] {gap: 0.5rem;}
</style>
"""


# --------------------------------------------------------------------------- #
# Cache / utilidades
# --------------------------------------------------------------------------- #


@st.cache_data(show_spinner=False, max_entries=200)
def as_image(data: bytes) -> Image.Image:
    """Bytes -> imagen RGB (con orientación EXIF corregida)."""
    img = Image.open(io.BytesIO(data))
    return ImageOps.exif_transpose(img).convert("RGB")


@st.cache_data(show_spinner=False, max_entries=48)
def build_collage(
    template: str,
    aspect: str,
    items: tuple[tuple[int, bytes], ...],
    margin: int,
    gap: int,
    radius: int,
    background: str,
    caption: str,
    bg_preset: str | None,
    bg_image: bytes | None,
    bg_blur: float,
    bg_dim: float,
    fmt: str,
    max_side: int | None,
    font: str = "bold",
) -> bytes:
    images = {idx: as_image(data) for idx, data in items}
    style = Style(
        margin=margin,
        gap=gap,
        radius=radius,
        background=background,
        caption=caption,
        font=font,
        transforms=dict(st.session_state.get("transforms") or {}),
        background_preset=bg_preset,
        background_image=as_image(bg_image) if bg_image else None,
        background_blur=float(bg_blur),
        background_dim=float(bg_dim),
    )
    canvas = render_collage(template, aspect, images, style)
    if fmt == "JPEG":
        return to_jpeg(canvas, quality=90, max_side=max_side)
    return to_png(canvas)


@st.cache_data(show_spinner=False, max_entries=200)
def thumb(data: bytes, size: int = 400) -> bytes:
    """Miniatura cuadrada para la rejilla (recorte centrado)."""
    img = ImageOps.fit(as_image(data), (size, size), method=Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=64)
def b64_card(img_bytes: bytes, width: int = 380, height: int = 290) -> str:
    """Imagen -> data URI base64 para usarla como fondo de una tarjeta."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img = ImageOps.fit(img, (width, height), method=Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=76, optimize=True, progressive=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def prepare(data: bytes, max_side: int = 1800) -> bytes:
    """Normaliza la foto (orientación + tamaño) para no llenar la sesión."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True)
    return buf.getvalue()


def first_empty(total: int, photos: dict[int, bytes], start: int = 0) -> int | None:
    for step in range(total):
        idx = (start + step) % total
        if idx not in photos:
            return idx
    return None


def resolve_number(country: str, written: str) -> tuple[str, str | None]:
    """Devuelve (numero_solo_digitos, error)."""
    dial = COUNTRIES[country]
    raw = re.sub(r"\D", "", written or "")
    if not raw:
        return "", "Escribe el número."
    local = raw.lstrip("0")
    if not dial and len(raw) < 10:
        return raw, "Con «Otro país» incluye el código (ej. 51987654321)."
    if dial and raw.startswith(dial) and len(raw) - len(dial) >= 7:
        full = raw  # el usuario ya incluyó el código de país
    elif dial:
        full = dial + local
    else:
        full = raw
    if not 8 <= len(full) <= 15:
        return full, "El número no parece válido (revisa el código de país)."
    return full, None


def share_widget(image_bytes: bytes, filename: str, text: str, height: int = 190) -> None:
    """Iframe con Web Share API: comparte el archivo real en el móvil."""
    payload = json.dumps(
        {
            "b64": base64.b64encode(image_bytes).decode("ascii"),
            "name": filename,
            "text": text,
        },
        ensure_ascii=True,
    )
    html = f"""
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body {{ margin: 0; font-family: -apple-system, system-ui, 'Segoe UI', sans-serif; background: transparent; }}
  button {{ width: 100%; padding: 14px; border: 0; border-radius: 14px; background: #25D366;
            color: #06281a; font-size: 16px; font-weight: 800; cursor: pointer; }}
  button:active {{ transform: scale(.99); }}
  p {{ font-size: 12.5px; margin: 9px 2px 0; color: #4b5563; text-align: center; line-height: 1.35; }}
</style></head>
<body>
  <button id="b">📲 Abrir menú de compartir</button>
  <p id="m">Elige WhatsApp en el menú y luego el contacto.</p>
<script>
  const CFG = {payload};
  document.getElementById('b').addEventListener('click', async () => {{
    const msg = document.getElementById('m');
    try {{
      const bin = atob(CFG.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const file = new File([bytes], CFG.name, {{type: 'image/jpeg'}});
      if (navigator.canShare && navigator.canShare({{files: [file]}})) {{
        await navigator.share({{files: [file], text: CFG.text, title: 'Collage'}});
        msg.textContent = 'Compartido ✅';
      }} else {{
        msg.textContent = 'Este navegador no comparte archivos. Descarga la imagen y adjúntala en el chat.';
      }}
    }} catch (err) {{
      msg.textContent = err.name === 'AbortError' ? 'Cancelado.' : ('No se pudo compartir: ' + err.message);
    }}
  }});
</script>
</body></html>
"""
    if hasattr(st, "iframe"):  # Streamlit >= 1.66
        st.iframe(html, height=height)
    else:  # compatibilidad
        components.html(html, height=height)


def step_header(number: int, title: str, hint: str = "") -> None:
    st.markdown(f"#### {number}. {title}")
    if hint:
        st.caption(hint)


# --------------------------------------------------------------------------- #
# Tarjetas visuales (botones con imagen de fondo)
# --------------------------------------------------------------------------- #


def card_css(key: str, label: str, image_b64: str, selected: bool) -> str:
    """CSS de una tarjeta: imagen de fondo + nombre al pie + check si va elegida."""
    ring = ""
    if selected:
        ring = f"""
.st-key-{key} button,
.st-key-{key} button:focus {{
  box-shadow: 0 0 0 3px #25D366, 0 12px 28px rgba(37,211,102,.32) !important;
  transform: translateY(-2px) scale(1.02) !important;
}}
.st-key-{key} button::before {{
  content: "✓"; position: absolute; top: 6px; right: 6px; z-index: 2;
  width: 22px; height: 22px; border-radius: 50%;
  background: #25D366; color: #06301d; font-size: 13px; font-weight: 900;
  display: grid; place-items: center;
  box-shadow: 0 2px 8px rgba(0,0,0,.30);
  animation: pop .18s ease-out;
}}
@keyframes pop {{
  from {{ transform: scale(.4); opacity: 0; }}
  to {{ transform: scale(1); opacity: 1; }}
}}
"""
    return f"""
.st-key-{key} [data-testid="stButton"] {{width: 100% !important;}}
.st-key-{key} button {{
  background-image: url("data:image/jpeg;base64,{image_b64}") !important;
  background-size: cover !important;
  background-position: center !important;
  background-repeat: no-repeat !important;
  background-color: #EDF1F6 !important;
  border: 0 !important;
  border-radius: 16px !important;
  width: 100% !important;
  height: auto !important;
  min-height: 62px !important;
  aspect-ratio: 4 / 3;
  padding: 0 !important;
  position: relative;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(16,24,40,.08), 0 6px 16px rgba(16,24,40,.10) !important;
  transition: transform .16s ease, box-shadow .16s ease;
}}
.st-key-{key} button:hover {{
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(16,24,40,.18) !important;
}}
.st-key-{key} button:active {{ transform: scale(.985); }}
.st-key-{key} button p,
.st-key-{key} button span {{ font-size: 0 !important; line-height: 0 !important; margin: 0 !important; }}
.st-key-{key} button > div {{ padding: 0 !important; }}
.st-key-{key} button::after {{
  content: "{label}";
  position: absolute; left: 0; right: 0; bottom: 0;
  padding: 18px 4px 6px;
  font-size: 11px; font-weight: 700; color: #fff; text-align: center;
  letter-spacing: .01em; white-space: nowrap; overflow: hidden;
  background: linear-gradient(to top, rgba(8,12,20,.78), rgba(8,12,20,0));
  pointer-events: none;
}}
{ring}"""


def card_gallery(
    options: list[dict],
    grid_key: str,
    mobile_cols: int,
    desktop_cols: int,
    selected: str,
    on_pick,
) -> None:
    """Rejilla de tarjetas clicables (imagen + etiqueta).

    Usa CSS grid en un contenedor propio: las columnas de Streamlit se apilan
    en pantallas de móvil y aquí necesitamos una rejilla real.
    """
    css = "".join(
        card_css(o["key"], o["label"], o["img"], o["id"] == selected)
        for o in options
    )
    st.markdown(
        f"""<style>
.st-key-{grid_key} {{
  display: grid !important;
  grid-template-columns: repeat({mobile_cols}, minmax(0, 1fr));
  gap: .55rem .45rem;
  align-items: start;
}}
.st-key-{grid_key} > [data-testid="stElementContainer"] {{
  width: 100% !important; margin: 0 !important;
}}
@media (min-width: 620px) {{
  .st-key-{grid_key} {{grid-template-columns: repeat({desktop_cols}, minmax(0, 1fr));}}
}}
{css}
</style>""",
        unsafe_allow_html=True,
    )
    with st.container(key=grid_key):
        for opt in options:
            if st.button(opt["label"], key=opt["key"], width="stretch"):
                on_pick(opt["id"])


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #

st.session_state.setdefault("album", {})      # plantilla -> {indice: bytes}
st.session_state.setdefault("target", {})     # plantilla -> siguiente hueco
st.session_state.setdefault("shot", 0)        # reinicia el widget de cámara
st.session_state.setdefault("up_handled", {}) # subidas ya procesadas
st.session_state.setdefault("template", "4 fotos · cuadrícula")
st.session_state.setdefault("bg", "blanco")   # preset | __custom__ | __color__
st.session_state.setdefault("bg_custom", None)
st.session_state.setdefault("bg_custom_src", None)
st.session_state.setdefault("bg_blur", 14)
st.session_state.setdefault("bg_dim", 18)
st.session_state.setdefault("bg_color", "#FFFFFF")
st.session_state.setdefault("font", "bold")   # fuente del texto del collage
st.session_state.setdefault("transforms", {}) # rotacion / ajuste por foto (slot -> (rot, zoom))

st.markdown(CSS, unsafe_allow_html=True)
st.markdown(
    """
<div style="background:linear-gradient(135deg,#25D366 0%,#128C7E 100%);
            border-radius:22px;padding:22px 24px;color:#fff;margin-bottom:16px">
  <div style="font-size:27px;font-weight:800;letter-spacing:-.03em">📸 Collage Express</div>
  <div style="opacity:.95;font-size:14.5px;margin-top:6px">
    Elige una plantilla, toca para tomar cada foto y compártelo por WhatsApp.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# 1. Plantilla (galería visual)
# --------------------------------------------------------------------------- #

step_header(
    1,
    "Elige la plantilla",
    "Toca la que más te guste: puedes cambiarla sin perder las fotos.",
)


def pick_layout(layout: str) -> None:
    st.session_state.template = layout
    st.rerun()


layout_options = [
    {
        "id": layout,
        "label": LAYOUT_LABELS.get(layout, layout),
        "key": f"card_tpl_{index}",
        "img": b64_card(to_png(layout_thumbnail(layout)), 380, 290),
    }
    for index, layout in enumerate(LAYOUTS)
]

card_gallery(
    layout_options,
    grid_key="grid_tpl",
    mobile_cols=4,
    desktop_cols=4,
    selected=st.session_state.template,
    on_pick=pick_layout,
)

template = st.session_state.template

# ---- Formato como tarjetas visuales (no barra) ----
step_header(
    1.5,
    "Formato del collage",
    "Toca la opción: la miniatura muestra la proporción real.",
)

ASPECT_LABELS = {
    "1:1": "Cuadrado\n(Instagram Post)",
    "4:5": "Vertical\n(Instagram Portrait)",
    "9:16": "Stories / Reels\n(TikTok, WhatsApp Status)",
    "16:9": "Panor\u00e1mico\n(YouTube, TV)",
    "2:3": "Vertical grande\n(Story / Reel largo)",
    "16:10": "Horizontal\n(wallpaper escritorio / TV)",
}


def pick_aspect(aspect_key: str) -> None:
    st.session_state.aspect = aspect_key
    st.rerun()

# miniaturas generadas en caliente: cada tarjeta muestra la proporción exacta
aspect_options = [
    {
        "id": a_key,
        "label": ASPECT_LABELS.get(a_key, a_key),
        "key": f"card_asp_{a_key.replace(':', '_')}",
        "img": b64_card(to_png(aspect_thumbnail(a_key, 380, 290)), 380, 290),
    }
    for a_key in ASPECTS
]
# (opciones de formato generadas directamente desde ASPECTS: una tarjeta por formato)
# si no existe en session_state, inicializo
st.session_state.setdefault("aspect", "1:1")

card_gallery(
    aspect_options,
    grid_key="grid_aspect",
    mobile_cols=2,
    desktop_cols=4,
    selected=st.session_state.aspect,
    on_pick=pick_aspect,
)

aspect = st.session_state.aspect

total = len(LAYOUTS[template])
album: dict[str, dict[int, bytes]] = st.session_state.album
photos = album.setdefault(template, {})

# Hueco objetivo: el elegido al borrar o el primero libre.
target = st.session_state.target.get(template)
if target is None or target >= total or target in photos:
    target = first_empty(total, photos)
st.session_state.target[template] = target

# --------------------------------------------------------------------------- #
# 2. Fotos
# --------------------------------------------------------------------------- #

if target is None:
    step_header(
        2,
        "Toma las fotos",
        "Todas las fotos están listas. Para cambiar una, toca 🗑 en su miniatura.",
    )
else:
    step_header(
        2,
        "Toma las fotos",
        f"La cámara llena el hueco {target + 1} de {total}. Cada foto se coloca sola en su lugar.",
    )

filled = len(photos)
st.progress(filled / total, text=f"{filled} de {total} fotos")
# Permite compartir el collage (con imagen) o solo el texto.
puede_compartir = filled > 0

if target is not None:
    shot = st.camera_input(
        f"📷 Foto {target + 1} de {total} — toca el botón de la cámara",
        key=f"cam_{template}_{target}_{st.session_state.shot}",
        resolution="1080p",
    )
    if shot is not None:
        photos[target] = prepare(shot.getvalue())
        st.session_state.target[template] = first_empty(total, photos, target + 1)
        st.session_state.shot += 1
        st.toast(f"Foto {target + 1} capturada ✅", icon="📸")
        st.rerun()
else:
    st.success("¡Collage completo! Baja para descargarlo o enviarlo por WhatsApp. 👇")

# Miniaturas
if filled:
    st.caption("Toca 🗑 para repetir una foto: la próxima captura ocupa ese hueco.")
    per_row = min(3, total)
    with st.container(key="thumbs"):
        for start in range(0, total, per_row):
            cols = st.columns(per_row, gap="small")
            for offset, col in enumerate(cols):
                idx = start + offset
                if idx >= total:
                    continue
                with col:
                    if idx in photos:
                        st.image(thumb(photos[idx]), width="stretch")
                        t = dict(st.session_state.get("transforms") or {})
                        br1, br2, br3, br4 = st.columns(4, gap="small")
                        with br1:
                            if st.button("⟲", key=f"rotL_{idx}", help="Rotar a la izquierda 90°"):
                                r, z = t.get(idx, (0, 1.0))
                                t[idx] = ((r - 90) % 360, z)
                                st.session_state["transforms"] = t
                                st.rerun()
                        with br2:
                            if st.button("⟳", key=f"rotR_{idx}", help="Rotar a la derecha 90°"):
                                r, z = t.get(idx, (0, 1.0))
                                t[idx] = ((r + 90) % 360, z)
                                st.session_state["transforms"] = t
                                st.rerun()
                        with br3:
                            if st.button("🔍+", key=f"zoomP_{idx}", help="Acercar la foto"):
                                r, z = t.get(idx, (0, 1.0))
                                t[idx] = (r, min(3.0, round(z * 1.25, 2)))
                                st.session_state["transforms"] = t
                                st.rerun()
                        with br4:
                            if st.button("🔍−", key=f"zoomM_{idx}", help="Alejar la foto"):
                                r, z = t.get(idx, (0, 1.0))
                                t[idx] = (r, max(0.5, round(z / 1.25, 2)))
                                st.session_state["transforms"] = t
                                st.rerun()
                        if st.button(
                            "🗑", key=f"del_{template}_{idx}", help="Repetir esta foto"
                        ):
                            photos.pop(idx, None)
                            st.session_state.target[template] = idx
                            st.rerun()
                    else:
                        st.markdown(
                            f"<div style='aspect-ratio:1;border:2px dashed #cfd8e3;border-radius:12px;"
                            f"display:flex;align-items:center;justify-content:center;color:#9aa6b6;"
                            f"font-weight:700'>{idx + 1}</div>",
                            unsafe_allow_html=True,
                        )

with st.expander("🖼️ O sube fotos desde la galería"):
    uploads = st.file_uploader(
        "Imágenes",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"up_{template}",
    )
    if uploads:
        marks = st.session_state.up_handled.setdefault(template, [])
        added = 0
        for file in uploads:
            mark = f"{file.name}:{file.size}"
            if mark in marks:
                continue
            free = first_empty(total, photos)
            if free is None:
                st.warning("Ya están todos los huecos ocupados. Borra una foto para reemplazarla.")
                break
            photos[free] = prepare(file.getvalue())
            marks.append(mark)
            added += 1
        if added:
            st.rerun()

# --------------------------------------------------------------------------- #
# 3. Fondo (galería visual + imagen propia)
# --------------------------------------------------------------------------- #

step_header(
    3,
    "Elige el fondo",
    "Toca una tarjeta. También puedes usar una foto tuya de fondo.",
)

if st.session_state.bg_custom:
    custom_img = b64_card(thumb(st.session_state.bg_custom, 900), 380, 290)
else:
    custom_img = b64_card(to_png(custom_thumbnail()), 380, 290)

bg_options = [
    {
        "id": "__custom__",
        "label": "Tu foto",
        "key": "card_bg_custom",
        "img": custom_img,
    },
    {
        "id": "__color__",
        "label": "Color",
        "key": "card_bg_color",
        "img": b64_card(to_png(color_thumbnail()), 380, 290),
    },
]

for slug, spec in PRESETS.items():
    bg_options.append(
        {
            "id": slug,
            "label": spec["label"],
            "key": f"card_bg_{slug}",
            "img": b64_card(to_png(preset_thumbnail(slug, 380, 290)), 380, 290),
        }
    )


def pick_background(bg_id: str) -> None:
    st.session_state.bg = bg_id
    if bg_id == "__custom__" and not st.session_state.bg_custom:
        st.session_state.bg_blur = max(10, st.session_state.bg_blur)
    st.rerun()


card_gallery(
    bg_options,
    grid_key="grid_bg",
    mobile_cols=3,
    desktop_cols=4,
    selected=st.session_state.bg,
    on_pick=pick_background,
)

bg_choice = st.session_state.bg

if bg_choice == "__custom__":
    up_bg = st.file_uploader(
        "Imagen de fondo",
        type=["jpg", "jpeg", "png", "webp"],
        label_visibility="collapsed",
        key="bg_upload",
    )
    if up_bg is not None:
        mark = (up_bg.name, up_bg.size)
        if st.session_state.bg_custom_src != mark:
            st.session_state.bg_custom = prepare(up_bg.getvalue(), max_side=2000)
            st.session_state.bg_custom_src = mark
            st.session_state.bg = "__custom__"
            st.rerun()
    if st.session_state.bg_custom:
        b1, b2 = st.columns(2)
        b1.slider(
            "Difuminar",
            0,
            60,
            key="bg_blur",
            help="Difumina el fondo para que las fotos resalten.",
        )
        b2.slider(
            "Oscurecer",
            0,
            70,
            key="bg_dim",
            help="Baja la luz del fondo y da contraste a las fotos.",
        )
        st.caption("💡 Sube una foto nítida y difumínala un poco: el collage gana elegancia.")
        if st.button("Quitar imagen de fondo", width="stretch"):
            st.session_state.bg_custom = None
            st.session_state.bg_custom_src = None
            st.session_state.bg = "blanco"
            st.rerun()
    else:
        st.info("Sube una imagen (paisaje, textura, una foto del local…) y la usamos de fondo.")

elif bg_choice == "__color__":
    st.color_picker("Color del fondo", key="bg_color")

# --------------------------------------------------------------------------- #
# 4. Ajustes finos
# --------------------------------------------------------------------------- #

margin, gap, radius, caption = 48, 18, 30, ""

with st.expander("🎛️ 4. Ajustes finos", expanded=False):
    c1, c2 = st.columns(2)
    margin = c1.slider("Margen", 0, 100, 48, step=2)
    gap = c2.slider("Separación", 0, 40, 18, step=1)
    radius = st.slider("Esquinas redondeadas", 0, 90, 30, step=2)
    font = st.selectbox(
        "Fuente del texto",
        list(FONT_LABELS.keys()),
        index=0,
        format_func=lambda f: FONT_LABELS.get(f, f),
    )
    caption = st.text_input(
        "Texto al pie (opcional)",
        max_chars=70,
        placeholder="Ej: Nuestro viaje a Cusco · 2026",
    )

# --------------------------------------------------------------------------- #
# 5. Vista previa
# --------------------------------------------------------------------------- #

if st.session_state.bg == "__custom__":
    bg_preset, bg_image = None, st.session_state.bg_custom
elif st.session_state.bg == "__color__":
    bg_preset, bg_image = None, None
else:
    bg_preset, bg_image = st.session_state.bg, None

background_color = st.session_state.bg_color if st.session_state.bg == "__color__" else "#FFFFFF"
bg_blur = float(st.session_state.bg_blur)
bg_dim = float(st.session_state.bg_dim)

items = tuple(sorted((idx, data) for idx, data in photos.items()))
signature = hashlib.sha1(
    repr(
        (
            template,
            aspect,
            margin,
            gap,
            radius,
            background_color,
            caption,
            font,
            {k: v for k, v in sorted((st.session_state.get("transforms") or {}).items())},
            bg_preset,
            hashlib.sha1(bg_image).hexdigest() if bg_image else None,
            bg_blur,
            bg_dim,
            tuple((idx, hashlib.sha1(data).hexdigest()) for idx, data in items),
        )
    ).encode()
).hexdigest()

if st.session_state.get("share_sig") != signature:
    st.session_state.pop("share_payload", None)
    st.session_state["share_sig"] = signature

step_header(5, "Así va quedando", "Se actualiza automáticamente con cada foto o cambio de fondo.")

args = dict(
    margin=margin,
    gap=gap,
    radius=radius,
    background=background_color,
    caption=caption,
    font=font,
    bg_preset=bg_preset,
    bg_image=bg_image,
    bg_blur=bg_blur,
    bg_dim=bg_dim,
)

preview_png = build_collage(template, aspect, items, fmt="PNG", max_side=None, **args)
st.image(preview_png, width="stretch")

# --------------------------------------------------------------------------- #
# 6. Descarga y WhatsApp
# --------------------------------------------------------------------------- #

step_header(6, "Descarga y comparte")

stamp = datetime.now().strftime("%Y%m%d-%H%M")
base_name = f"collage-{stamp}"

d1, d2 = st.columns(2)
d1.download_button(
    "⬇️ PNG (máxima calidad)",
    data=preview_png,
    file_name=f"{base_name}.png",
    mime="image/png",
    width="stretch",
    disabled=filled == 0,
)
d2.download_button(
    "⬇️ JPG (ligero)",
    data=build_collage(template, aspect, items, fmt="JPEG", max_side=2000, **args),
    file_name=f"{base_name}.jpg",
    mime="image/jpeg",
    width="stretch",
    disabled=filled == 0,
)

if filled < total:
    st.caption(f"Faltan {total - filled} foto(s). Puedes descargarlo igual, con los huecos numerados.")

st.divider()
st.markdown("**Enviar por WhatsApp**")

w1, w2 = st.columns([1.4, 2])
country = w1.selectbox("País", list(COUNTRIES), index=0, label_visibility="visible")
written = w2.text_input(
    "Número",
    placeholder="987 654 321",
    help="Sin el código de país si elegiste uno arriba.",
)

number, error = resolve_number(country, written)
message = st.text_input(
    "Mensaje (opcional)",
    value="Te comparto este collage 📸",
    max_chars=300,
)

if not written.strip():
    st.button("💬 Abrir chat de WhatsApp", disabled=True, width="stretch")
    st.caption("Escribe el número arriba y pulsa Enter para generar el enlace.")
elif error:
    st.button("💬 Abrir chat de WhatsApp", disabled=True, width="stretch")
    st.caption(f"⚠️ {error}")
elif st.button("💬 Abrir chat de WhatsApp", width="stretch", disabled=not puede_compartir):
    # Botón principal: genera el collage y lo envía CON la imagen + el texto.
    st.session_state["share_payload"] = build_collage(
        template, aspect, items, fmt="JPEG", max_side=1600, **args
    )
elif filled == 0:
    # Sin foto todavia: solo texto por el enlace wa.me (la imagen se agrega desde el chat).
    link = f"https://wa.me/{number}"
    if message.strip():
        link += f"?text={quote(message.strip())}"
    st.link_button(
        f"💬 Abrir chat de +{number}",
        link,
        type="primary",
        width="stretch",
    )

if st.session_state.get("share_payload"):
    share_widget(
        st.session_state["share_payload"],
        f"{base_name}.jpg",
        message.strip() or "Te comparto este collage 📸",
    )

with st.expander("📎 ¿Y la imagen? Cómo enviarla de verdad"):
    st.markdown(
        """
- **Botón principal (recomendado)**: cuando ya tienes fotos, **«Abrir chat de WhatsApp»** genera el collage
  y envía **imagen + texto** en un solo paso (menú de compartir → WhatsApp).
- **Solo texto**: usa el botón de abajo; el enlace `wa.me` abre el chat con el número y el mensaje escrito,
  pero **WhatsApp no acepta adjuntar archivos desde un link**. La foto se adjunta dentro del chat.
- **PC**: descarga el JPG y arrástralo al chat de WhatsApp Web.
- **Envío 100 % automático**: requiere la *WhatsApp Cloud API* (cuenta de Meta Business, token y plantilla
  aprobada). No se puede con solo un número; se configura aparte.
"""
    )

st.divider()
with st.expander("♻️ Reiniciar / opciones", expanded=False):
    if st.button("Reiniciar todo (borra fotos y fondo)", width="stretch"):
        st.session_state.album = {}
        st.session_state.target = {}
        st.session_state.shot = 0
        st.session_state.up_handled = {}
        st.session_state.bg = "blanco"
        st.session_state.bg_custom = None
        st.session_state.bg_custom_src = None
        st.session_state.bg_blur = 14
        st.session_state.bg_dim = 18
        st.session_state.bg_color = "#FFFFFF"
        st.session_state.template = "4 fotos · cuadrícula"
        st.session_state.transforms = {}
        st.rerun()
    st.caption("Las fotos viven solo en esta sesión: recargar la página también las borra.")

with st.expander("☁️ Cómo subirlo a Streamlit (2 minutos)"):
    st.markdown(
        """
1. Crea un repositorio en GitHub y sube **`app.py`**, **`collage.py`** y **`requirements.txt`**.
2. Entra a [share.streamlit.io](https://share.streamlit.io) → **Create app** → elige el repo.
3. *Main file path*: `app.py` → **Deploy**.
4. Listo: obtienes una URL `https://algo.streamlit.app` con **HTTPS**, obligatorio para que la cámara
   funcione en el celular.

> En local: `pip install -r requirements.txt` y `streamlit run app.py`.
> La cámara funciona en `http://localhost` o en cualquier dominio HTTPS.
"""
    )

st.caption(
    "🔒 Las fotos viven solo en la sesión del navegador (memoria del servidor) y se borran al cerrar o recargar."
)
