"""Leer el texto de un PDF y sacar las imágenes de un PDF escaneado."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def texto_pdf(ruta: str | Path) -> str:
    """Texto de todas las páginas. Vacío si el PDF es una foto escaneada."""
    lector = PdfReader(str(ruta))
    return "\n".join((p.extract_text() or "").strip() for p in lector.pages).strip()


def es_escaneado(ruta: str | Path, minimo: int = 20) -> bool:
    return len(texto_pdf(ruta)) < minimo


def imagenes_pdf(ruta: str | Path, limite: int = 5) -> list[tuple[str, bytes]]:
    """Imágenes incrustadas (útil para PDF escaneados). Devuelve (mime, bytes)."""
    salida: list[tuple[str, bytes]] = []
    for pagina in PdfReader(str(ruta)).pages:
        for img in pagina.images:
            ext = Path(img.name).suffix.lower().lstrip(".") or "png"
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            salida.append((mime, img.data))
            if len(salida) >= limite:
                return salida
    return salida
