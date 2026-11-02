"""Une todo: abre el archivo, elige cómo leerlo y devuelve una factura validada."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .factura import Factura, desde_dict, validar
from .imagenes import EXTENSIONES
from .proveedores import Documento, obtener
from .texto import imagenes_pdf, texto_pdf


def preparar(ruta: str | Path) -> Documento:
    ruta = Path(ruta)
    sufijo = ruta.suffix.lower()
    if sufijo == ".pdf":
        texto = texto_pdf(ruta)
        if len(texto) >= 20:
            return Documento(texto=texto)
        # PDF escaneado: mandamos el PDF (Gemini) y sus imágenes (OpenAI / Ollama)
        return Documento(pdf=ruta.read_bytes(), imagenes=imagenes_pdf(ruta))
    if sufijo in EXTENSIONES:
        mime = mimetypes.guess_type(ruta.name)[0] or "image/jpeg"
        return Documento(imagenes=[(mime, ruta.read_bytes())])
    raise ValueError(f"Formato no soportado: {ruta.suffix}")


def leer_factura(ruta: str | Path, ia: str = "reglas", modelo: str | None = None,
                 clave: str | None = None) -> Factura:
    proveedor = obtener(ia, modelo=modelo, clave=clave)
    return validar(desde_dict(proveedor.extraer(preparar(ruta))))
