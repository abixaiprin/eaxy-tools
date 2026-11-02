"""Línea de comandos: `eaxy img2pdf`, `eaxy texto`, `eaxy factura`, `eaxy servir`."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import __version__
from .documentos import leer_factura
from .imagenes import imagenes_a_pdf
from .proveedores import PROVEEDORES
from .texto import texto_pdf


def _img2pdf(a) -> int:
    salida = imagenes_a_pdf(a.imagenes, a.salida, pagina=a.pagina, margen_mm=a.margen)
    print(f"✓ PDF creado: {salida}")
    return 0


def _texto(a) -> int:
    print(texto_pdf(a.pdf) or "(sin texto: parece un PDF escaneado; usa `eaxy factura --ia gemini`)")
    return 0


def _factura(a) -> int:
    archivos = []
    for r in map(Path, a.archivos):
        archivos += sorted(p for p in r.iterdir() if p.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png", ".webp")) if r.is_dir() else [r]
    resultados = []
    for archivo in archivos:
        try:
            f = leer_factura(archivo, ia=a.ia, modelo=a.modelo).a_dict()
        except Exception as e:  # una factura mala no detiene el lote
            f = {"error": str(e)}
        resultados.append({"archivo": str(archivo), **f})
        for aviso in f.get("avisos", []):
            print(f"⚠ {archivo.name}: {aviso}", file=sys.stderr)
    if a.csv:
        campos = ["archivo", "numero", "fecha", "moneda", "subtotal", "iva", "total", "proveedor_rif", "proveedor_nombre", "error"]
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
            w.writeheader()
            for r in resultados:
                prov = r.get("proveedor") or {}
                w.writerow({**r, "proveedor_rif": prov.get("rif"), "proveedor_nombre": prov.get("nombre")})
        print(f"✓ CSV creado: {a.csv} ({len(resultados)} facturas)")
    else:
        print(json.dumps(resultados[0] if len(resultados) == 1 else resultados, ensure_ascii=False, indent=2))
    return 0


def _servir(a) -> int:
    try:
        import uvicorn
    except ImportError:
        print("Instala la API con: pip install 'eaxy-tools[api]'", file=sys.stderr)
        return 1
    uvicorn.run("eaxy.api:app", host=a.host, port=a.puerto)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eaxy", description="Eaxy Tools: herramientas que te ahorran trabajo.")
    p.add_argument("--version", action="version", version=f"eaxy-tools {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("img2pdf", help="unir fotos o capturas en un PDF")
    s.add_argument("imagenes", nargs="+", help="imágenes o carpetas")
    s.add_argument("-o", "--salida", default="documento.pdf")
    s.add_argument("--pagina", choices=["a4", "carta", "original"], default="a4")
    s.add_argument("--margen", type=float, default=10, help="margen en mm (por defecto 10)")
    s.set_defaults(fn=_img2pdf)

    s = sub.add_parser("texto", help="leer el texto de un PDF")
    s.add_argument("pdf")
    s.set_defaults(fn=_texto)

    s = sub.add_parser("factura", help="convertir facturas (PDF o foto) en datos")
    s.add_argument("archivos", nargs="+", help="archivos o carpetas")
    s.add_argument("--ia", choices=list(PROVEEDORES), default="reglas",
                   help="reglas (sin IA), openai, gemini u ollama (local)")
    s.add_argument("--modelo", help="modelo del proveedor (opcional)")
    s.add_argument("--csv", help="guardar el resultado en un CSV")
    s.set_defaults(fn=_factura)

    s = sub.add_parser("servir", help="levantar la API HTTP")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--puerto", type=int, default=8000)
    s.set_defaults(fn=_servir)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
