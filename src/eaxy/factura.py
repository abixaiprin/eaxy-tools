"""Esquema de factura, limpieza y validación (pensado para Venezuela y LATAM)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

# RIF venezolano: letra + 8 dígitos + dígito verificador. Ej.: J-12345678-9
RIF_RE = re.compile(r"\b([VEJPG])[-\s.]?(\d{8})[-\s.]?(\d)\b", re.IGNORECASE)

ESQUEMA = {
    "proveedor": {"nombre": "texto", "rif": "J-12345678-9"},
    "cliente": {"nombre": "texto", "rif": "V-12345678-9"},
    "numero": "texto",
    "numero_control": "texto",
    "fecha": "AAAA-MM-DD",
    "moneda": "VES | USD | EUR",
    "items": [{"descripcion": "texto", "cantidad": 1, "precio_unitario": 0.0, "total": 0.0}],
    "subtotal": 0.0,
    "iva": 0.0,
    "total": 0.0,
}

INSTRUCCIONES = (
    "Eres un extractor de datos de facturas. Devuelve SOLO un objeto JSON con esta forma "
    f"exacta: {json.dumps(ESQUEMA, ensure_ascii=False)}. "
    "Usa null si un dato no aparece. Los montos van como números con punto decimal, sin "
    "símbolos ni separadores de miles. No inventes datos."
)


@dataclass
class Item:
    descripcion: str = ""
    cantidad: float | None = None
    precio_unitario: float | None = None
    total: float | None = None


@dataclass
class Parte:
    nombre: str | None = None
    rif: str | None = None


@dataclass
class Factura:
    proveedor: Parte = field(default_factory=Parte)
    cliente: Parte = field(default_factory=Parte)
    numero: str | None = None
    numero_control: str | None = None
    fecha: str | None = None
    moneda: str | None = None
    items: list[Item] = field(default_factory=list)
    subtotal: float | None = None
    iva: float | None = None
    total: float | None = None
    avisos: list[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return asdict(self)


# ---------- limpieza ----------

def numero(valor) -> float | None:
    """Convierte '1.234,56', '1,234.56', 'Bs. 1234,5' o 12.5 a float."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = re.sub(r"[^\d,.\-]", "", str(valor))
    if not s:
        return None
    if "," in s and "." in s:
        # el último separador es el decimal
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        entero, _, dec = s.rpartition(",")
        s = f"{entero.replace(',', '')}.{dec}" if len(dec) <= 2 else s.replace(",", "")
    elif s.count(".") > 1:
        entero, _, dec = s.rpartition(".")
        s = f"{entero.replace('.', '')}.{dec}" if len(dec) <= 2 else s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def rif(valor) -> str | None:
    if not valor:
        return None
    m = RIF_RE.search(str(valor))
    return f"{m.group(1).upper()}-{m.group(2)}-{m.group(3)}" if m else None


def fecha(valor) -> str | None:
    if not valor:
        return None
    s = str(valor).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, formato).date().isoformat()
        except ValueError:
            pass
    return s


def desde_dict(datos: dict) -> Factura:
    """Construye una Factura limpia a partir del JSON que devuelve la IA o las reglas."""
    parte = lambda d: Parte(nombre=(d or {}).get("nombre"), rif=rif((d or {}).get("rif")))  # noqa: E731
    items = [
        Item(
            descripcion=str(i.get("descripcion") or "").strip(),
            cantidad=numero(i.get("cantidad")),
            precio_unitario=numero(i.get("precio_unitario")),
            total=numero(i.get("total")),
        )
        for i in (datos.get("items") or [])
        if isinstance(i, dict)
    ]
    moneda = (datos.get("moneda") or "").upper() or None
    if moneda in ("BS", "BS.", "BSD", "BSF", "VEF"):
        moneda = "VES"
    return Factura(
        proveedor=parte(datos.get("proveedor")),
        cliente=parte(datos.get("cliente")),
        numero=datos.get("numero"),
        numero_control=datos.get("numero_control"),
        fecha=fecha(datos.get("fecha")),
        moneda=moneda,
        items=items,
        subtotal=numero(datos.get("subtotal")),
        iva=numero(datos.get("iva")),
        total=numero(datos.get("total")),
    )


def json_de_respuesta(texto: str) -> dict:
    """Saca el primer objeto JSON de la respuesta de un modelo (tolera ```json ... ```)."""
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin == -1:
        raise ValueError("La respuesta no contiene JSON.")
    return json.loads(texto[inicio : fin + 1])


# ---------- validación ----------

def validar(f: Factura, tolerancia: float = 0.05) -> Factura:
    avisos = []
    if f.subtotal is not None and f.iva is not None and f.total is not None:
        if abs(f.subtotal + f.iva - f.total) > tolerancia:
            avisos.append(f"subtotal + IVA ({f.subtotal + f.iva:.2f}) no coincide con el total ({f.total:.2f})")
    sumas = [i.total for i in f.items if i.total is not None]
    if sumas and f.subtotal is not None and abs(sum(sumas) - f.subtotal) > tolerancia:
        avisos.append(f"la suma de los ítems ({sum(sumas):.2f}) no coincide con el subtotal ({f.subtotal:.2f})")
    if f.proveedor.rif is None:
        avisos.append("no se encontró un RIF válido del proveedor")
    if f.total is None:
        avisos.append("no se encontró el total")
    f.avisos = avisos
    return f


# ---------- extracción por reglas (sin IA) ----------

def _buscar(patron: str, texto: str) -> str | None:
    m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def _nombre_proveedor(texto: str) -> str | None:
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    for l in lineas:  # razón social típica: "Empresa C.A.", "S.A.", "S.R.L.", "F.P."
        if re.search(r"\b(C\.\s?A|S\.\s?A|S\.\s?R\.\s?L|F\.\s?P)\.?(\s|$)", l):
            return l
    for i, l in enumerate(lineas):  # si no, la línea anterior al primer RIF
        if RIF_RE.search(l):
            return lineas[i - 1] if i > 0 else None
    return lineas[0] if lineas else None


def por_reglas(texto: str) -> dict:
    """Extracción básica sin IA para facturas digitales con formato venezolano común."""
    rifs = [f"{a}-{b}-{c}" for a, b, c in RIF_RE.findall(texto)]
    monto = r"[:\s]*(?:Bs\.?|USD|\$|€)?\s*([\d.,]+)"
    datos = {
        "proveedor": {"nombre": _nombre_proveedor(texto),
                      "rif": rifs[0] if rifs else None},
        "cliente": {"nombre": _buscar(r"(?:cliente|raz[oó]n social)[:\s]+(.+)$", texto),
                    "rif": rifs[1] if len(rifs) > 1 else None},
        "numero": _buscar(r"factura\s*(?:n[°ºo.]*|#)\s*[:\s]*([\w-]+)", texto),
        "numero_control": _buscar(r"(?:n[°ºo.]*\s*de\s*)?control\s*(?:n[°ºo.]*)?[:\s]*([\w-]+)", texto),
        "fecha": _buscar(r"fecha(?:\s*de\s*emisi[oó]n)?[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texto),
        "moneda": "USD" if re.search(r"\bUSD\b|\$", texto) else ("VES" if re.search(r"\bBs\b", texto, re.I) else None),
        "subtotal": _buscar(r"sub\s*-?\s*total" + monto, texto),
        "iva": _buscar(r"\bI\.?V\.?A\.?\b\s*(?:\(?\d{1,2}(?:[.,]\d+)?\s*%\)?)?" + monto, texto),
        "total": _buscar(r"^\s*total(?:\s*a\s*pagar)?" + monto, texto),
        "items": [],
    }
    return datos
