"""Convertir imágenes (fotos, capturas, escaneos) a un solo PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}

# Tamaños de página en milímetros (ancho, alto) en vertical.
PAGINAS_MM = {"a4": (210.0, 297.0), "carta": (215.9, 279.4)}
DPI = 150


def listar_imagenes(rutas: Iterable[str | Path]) -> list[Path]:
    """Acepta archivos y carpetas; devuelve las imágenes en orden alfabético por carpeta."""
    salida: list[Path] = []
    for ruta in map(Path, rutas):
        if ruta.is_dir():
            salida += sorted(p for p in ruta.iterdir() if p.suffix.lower() in EXTENSIONES)
        elif ruta.suffix.lower() in EXTENSIONES:
            salida.append(ruta)
        else:
            raise ValueError(f"No es una imagen compatible: {ruta}")
    if not salida:
        raise ValueError("No se encontraron imágenes.")
    return salida


def _preparar(img: Image.Image, max_lado: int | None) -> Image.Image:
    img = ImageOps.exif_transpose(img)  # respeta la orientación de la foto del teléfono
    if img.mode in ("RGBA", "LA", "P"):
        fondo = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        fondo.paste(rgba, mask=rgba.split()[-1])
        img = fondo
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if max_lado and max(img.size) > max_lado:
        img.thumbnail((max_lado, max_lado), Image.LANCZOS)
    return img


def _en_pagina(img: Image.Image, pagina: str, margen_mm: float) -> Image.Image:
    ancho_mm, alto_mm = PAGINAS_MM[pagina]
    if img.width > img.height:  # imagen horizontal → página horizontal
        ancho_mm, alto_mm = alto_mm, ancho_mm
    px = lambda mm: round(mm / 25.4 * DPI)  # noqa: E731
    lienzo = Image.new("RGB", (px(ancho_mm), px(alto_mm)), "white")
    caja = (lienzo.width - 2 * px(margen_mm), lienzo.height - 2 * px(margen_mm))
    copia = img.copy()
    copia.thumbnail(caja, Image.LANCZOS)
    lienzo.paste(copia, ((lienzo.width - copia.width) // 2, (lienzo.height - copia.height) // 2))
    return lienzo


def imagenes_a_pdf(
    rutas: Iterable[str | Path],
    salida: str | Path,
    pagina: str = "a4",
    margen_mm: float = 10,
    max_lado: int | None = 2400,
) -> Path:
    """Une varias imágenes en un PDF. `pagina` puede ser "a4", "carta" u "original"."""
    if pagina not in (*PAGINAS_MM, "original"):
        raise ValueError("pagina debe ser a4, carta u original")
    paginas = []
    for ruta in listar_imagenes(rutas):
        with Image.open(ruta) as img:
            img = _preparar(img, max_lado)
            paginas.append(img if pagina == "original" else _en_pagina(img, pagina, margen_mm))
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    paginas[0].save(salida, "PDF", resolution=DPI, save_all=True, append_images=paginas[1:])
    return salida
