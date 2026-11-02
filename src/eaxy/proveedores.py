"""Proveedores de IA. Tú pones tu propia API key (o usas un modelo local con Ollama).

Para sumar otro proveedor: hereda de `Proveedor`, implementa `pedir()` y regístralo en
`PROVEEDORES`.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .factura import INSTRUCCIONES, json_de_respuesta, por_reglas


@dataclass
class Documento:
    """Lo que se le entrega al modelo: texto, imágenes o un PDF completo."""

    texto: str = ""
    imagenes: list[tuple[str, bytes]] | None = None  # (mime, bytes)
    pdf: bytes | None = None


def _post(url: str, cuerpo: dict, cabeceras: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json", **cabeceras},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"El proveedor respondió {e.code}: {detalle}") from None


class Proveedor:
    nombre = "base"
    variable_clave: str | None = None
    modelo_por_defecto = ""

    def __init__(self, modelo: str | None = None, clave: str | None = None):
        self.modelo = modelo or os.getenv("EAXY_MODELO") or self.modelo_por_defecto
        self.clave = clave or os.getenv("EAXY_API_KEY") or (
            os.getenv(self.variable_clave) if self.variable_clave else None
        )
        if self.variable_clave and not self.clave:
            raise RuntimeError(
                f"Falta la API key de {self.nombre}. Define {self.variable_clave} o EAXY_API_KEY."
            )

    def extraer(self, doc: Documento) -> dict:
        return json_de_respuesta(self.pedir(doc))

    def pedir(self, doc: Documento) -> str:  # pragma: no cover - lo implementa cada proveedor
        raise NotImplementedError


class Reglas(Proveedor):
    """Sin IA y sin costo: funciona con PDF que tienen texto."""

    nombre = "reglas"

    def extraer(self, doc: Documento) -> dict:
        if not doc.texto:
            raise RuntimeError("El documento no tiene texto. Usa --ia openai, gemini u ollama.")
        return por_reglas(doc.texto)


class OpenAI(Proveedor):
    nombre = "openai"
    variable_clave = "OPENAI_API_KEY"
    modelo_por_defecto = "gpt-4o-mini"
    url = "https://api.openai.com/v1/chat/completions"

    def pedir(self, doc: Documento) -> str:
        contenido: list[dict] = [{"type": "text", "text": doc.texto or "Extrae los datos de la factura."}]
        for mime, datos in doc.imagenes or []:
            b64 = base64.b64encode(datos).decode()
            contenido.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        r = _post(
            self.url,
            {
                "model": self.modelo,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": INSTRUCCIONES},
                    {"role": "user", "content": contenido},
                ],
            },
            {"Authorization": f"Bearer {self.clave}"},
        )
        return r["choices"][0]["message"]["content"]


class Gemini(Proveedor):
    nombre = "gemini"
    variable_clave = "GEMINI_API_KEY"
    modelo_por_defecto = "gemini-2.5-flash"

    def pedir(self, doc: Documento) -> str:
        partes: list[dict] = [{"text": INSTRUCCIONES}]
        if doc.texto:
            partes.append({"text": doc.texto})
        if doc.pdf:  # Gemini lee el PDF completo, incluso escaneado
            partes.append({"inline_data": {"mime_type": "application/pdf",
                                           "data": base64.b64encode(doc.pdf).decode()}})
        for mime, datos in doc.imagenes or []:
            partes.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(datos).decode()}})
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.modelo}:generateContent"
        r = _post(
            url,
            {"contents": [{"parts": partes}], "generationConfig": {"responseMimeType": "application/json"}},
            {"x-goog-api-key": self.clave},
        )
        return r["candidates"][0]["content"]["parts"][0]["text"]


class Ollama(Proveedor):
    """Modelo local y privado: los documentos no salen de tu computadora."""

    nombre = "ollama"
    modelo_por_defecto = "llama3.2-vision"

    def pedir(self, doc: Documento) -> str:
        base = os.getenv("OLLAMA_URL", "http://localhost:11434")
        mensaje = {"role": "user", "content": doc.texto or "Extrae los datos de la factura."}
        if doc.imagenes:
            mensaje["images"] = [base64.b64encode(d).decode() for _, d in doc.imagenes]
        r = _post(
            f"{base}/api/chat",
            {"model": self.modelo, "format": "json", "stream": False,
             "messages": [{"role": "system", "content": INSTRUCCIONES}, mensaje]},
            {},
            timeout=300,
        )
        return r["message"]["content"]


PROVEEDORES: dict[str, type[Proveedor]] = {
    p.nombre: p for p in (Reglas, OpenAI, Gemini, Ollama)
}


def obtener(nombre: str, modelo: str | None = None, clave: str | None = None) -> Proveedor:
    try:
        return PROVEEDORES[nombre](modelo=modelo, clave=clave)
    except KeyError:
        raise ValueError(f"Proveedor desconocido: {nombre}. Opciones: {', '.join(PROVEEDORES)}") from None
