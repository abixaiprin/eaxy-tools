"""API HTTP (opcional): la base de la futura versión en la nube.

Instala con `pip install "eaxy-tools[api]"` y ejecuta `eaxy servir`.
Docs interactivas en http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import __version__
from .documentos import leer_factura
from .imagenes import imagenes_a_pdf

app = FastAPI(title="Eaxy Tools API", version=__version__)
LIMITE_MB = 15


async def _guardar(archivo: UploadFile, carpeta: Path) -> Path:
    datos = await archivo.read()
    if len(datos) > LIMITE_MB * 1024 * 1024:
        raise HTTPException(413, f"El archivo supera {LIMITE_MB} MB")
    destino = carpeta / Path(archivo.filename or "archivo").name
    destino.write_bytes(datos)
    return destino


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok", "version": __version__}


@app.post("/v1/img2pdf")
async def img2pdf(imagenes: list[UploadFile] = File(...), pagina: str = Form("a4")):
    carpeta = Path(tempfile.mkdtemp(prefix="eaxy-"))
    rutas = [await _guardar(i, carpeta) for i in imagenes]
    try:
        salida = imagenes_a_pdf(rutas, carpeta / "documento.pdf", pagina=pagina)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return FileResponse(salida, media_type="application/pdf", filename="documento.pdf")


@app.post("/v1/factura")
async def factura(archivo: UploadFile = File(...), ia: str = Form("reglas"), modelo: str | None = Form(None)):
    carpeta = Path(tempfile.mkdtemp(prefix="eaxy-"))
    ruta = await _guardar(archivo, carpeta)
    try:
        return leer_factura(ruta, ia=ia, modelo=modelo).a_dict()
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e)) from None
