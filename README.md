# 📸 Collage Express → WhatsApp

App en **Streamlit** para armar un collage con la cámara del celular (o subiendo fotos),
descargarlo y compartirlo por WhatsApp a un número.

- 8 plantillas (1, 2, 3, 4, 5, 6 y 9 fotos).
- La cámara llena **sola** el siguiente hueco: se toca una vez por foto.
- Formatos: 1:1, 4:5, 9:16 y 16:9.
- Diseño ajustable: fondo, margen, separación, esquinas y texto al pie.
- Descarga en PNG (máxima) y JPG (ligero).
- Compartir: enlace `wa.me` al número escrito + botón de compartir nativo en el móvil.

---

## 1. Ejecutar en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Abre `http://localhost:8501`. La cámara funciona en `localhost` y en cualquier dominio
**HTTPS**; en `http://192.168.x.x` el navegador la bloquea.

## 2. Subir a Streamlit Community Cloud

1. Crea un repositorio en GitHub y sube el **contenido de esta carpeta**:
   `app.py`, `collage.py`, `requirements.txt` y `.streamlit/config.toml`.
2. Entra a <https://share.streamlit.io> → **Create app** → **Deploy a public app from GitHub**.
3. Repo + branch + *Main file path*: `app.py` → **Deploy**.
4. En 1–2 minutos tienes `https://<algo>.streamlit.app` con HTTPS, listo para el celular.

> La carpeta `tools/` es solo para desarrollo (capturas y preview). No hace falta subirla.

## 3. Estructura

| Archivo | Para qué |
|---|---|
| `app.py` | Interfaz: plantilla, cámara, estilo, descarga y WhatsApp |
| `collage.py` | Motor de imágenes con Pillow (plantillas, recorte, texto) |
| `requirements.txt` | `streamlit`, `pillow` |
| `.streamlit/config.toml` | Tema verde WhatsApp y barra de herramientas mínima |
| `tools/preview.py` | Hoja de contactos con todas las plantillas |
| `tools/shot.py` | Prueba end-to-end con cámara falsa de Chromium |

## 4. Cómo se envía a WhatsApp (importante)

Hay tres niveles y solo el último es 100 % automático:

1. **Enlace `wa.me/<número>`** (el botón verde): abre el chat con ese número y el mensaje
   escrito. WhatsApp **no permite adjuntar archivos desde un enlace**, así que la imagen se
   elige dentro del chat.
2. **Web Share API** (botón "Preparar envío directo"): en el móvil abre la hoja de compartir
   del sistema con la imagen ya cargada; eliges WhatsApp y el contacto. Requiere HTTPS y un
   navegador moderno (Chrome Android, Safari iOS). En escritorio no existe.
3. **WhatsApp Cloud API**: envío automático real, sin intervención. Necesita cuenta de Meta
   Business, número verificado, token permanente y una plantilla aprobada; la imagen se sube
   a `/media` y se manda por `/{phone_number_id}/messages`. Es un trámite aparte, no basta con
   escribir un número en la app.

## 5. Agregar una plantilla

En `collage.py` las plantillas son rectángulos normalizados `(x, y, ancho, alto)` de 0 a 1:

```python
LAYOUTS["2 fotos · antes / después"] = [
    (0.0, 0.0, 1.0, 0.5),
    (0.0, 0.5, 1.0, 0.5),
]
```

La app toma el número de huecos de la lista y genera el selector automáticamente.

## 6. Privacidad

Las fotos viven en `st.session_state` (memoria del servidor, atada a la sesión del navegador).
No se escriben en disco ni se envían a terceros; al recargar o cerrar la pestaña se pierden.
