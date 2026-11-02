import json

import pytest
from PIL import Image
from pypdf import PdfReader

from eaxy import factura as fx
from eaxy import proveedores
from eaxy.cli import main
from eaxy.documentos import leer_factura, preparar
from eaxy.imagenes import imagenes_a_pdf

FACTURA = [
    "Ferretería El Tornillo C.A.",
    "RIF: J-40123456-7",
    "Factura N° 000123",
    "N° de Control: 00-004567",
    "Fecha de emisión: 15/10/2026",
    "Cliente: Panadería La Esquina",
    "RIF: J-29876543-2",
    "Tornillos 3/8 x 100   2   Bs 500,00   Bs 1.000,00",
    "Subtotal: Bs 1.000,00",
    "IVA 16%: Bs 160,00",
    "Total a pagar: Bs 1.160,00",
]


@pytest.fixture
def pdf_factura(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    ruta = tmp_path / "factura.pdf"
    c = canvas.Canvas(str(ruta))
    for n, linea in enumerate(FACTURA):
        c.drawString(60, 780 - n * 18, linea)
    c.save()
    return ruta


@pytest.fixture
def fotos(tmp_path):
    rutas = []
    for n, (tam, modo) in enumerate([((1200, 800), "RGB"), ((600, 900), "RGBA")]):
        r = tmp_path / f"foto{n}.png"
        Image.new(modo, tam, (200, 50, 120)).save(r)
        rutas.append(r)
    return rutas


# ---------- limpieza ----------

@pytest.mark.parametrize("entrada,esperado", [
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("Bs. 1.160,00", 1160.0),
    ("$ 25", 25.0), ("1.000.000", 1000000.0), ("160,5", 160.5), (12, 12.0), ("", None), (None, None),
])
def test_numero(entrada, esperado):
    assert fx.numero(entrada) == esperado


def test_rif_y_fecha():
    assert fx.rif("j401234567") == "J-40123456-7"
    assert fx.rif("V 12345678 9") == "V-12345678-9"
    assert fx.rif("123") is None
    assert fx.fecha("15/10/2026") == "2026-10-15"


def test_json_de_respuesta_tolera_markdown():
    assert fx.json_de_respuesta('```json\n{"total": "10"}\n```') == {"total": "10"}


def test_validar_detecta_totales_que_no_cuadran():
    f = fx.validar(fx.desde_dict({"proveedor": {"rif": "J-40123456-7"}, "subtotal": 100, "iva": 16, "total": 120}))
    assert any("no coincide con el total" in a for a in f.avisos)


# ---------- imágenes a PDF ----------

def test_img2pdf_a4(fotos, tmp_path):
    salida = imagenes_a_pdf(fotos, tmp_path / "out.pdf")
    paginas = PdfReader(salida).pages
    assert len(paginas) == 2
    primera = paginas[0].mediabox
    assert float(primera.width) > float(primera.height)  # foto horizontal → página horizontal


def test_img2pdf_carpeta_original(fotos, tmp_path):
    salida = imagenes_a_pdf([tmp_path], tmp_path / "otro.pdf", pagina="original")
    assert len(PdfReader(salida).pages) == 2


def test_img2pdf_rechaza_no_imagen(tmp_path):
    (tmp_path / "x.txt").write_text("hola")
    with pytest.raises(ValueError):
        imagenes_a_pdf([tmp_path / "x.txt"], tmp_path / "o.pdf")


# ---------- facturas ----------

def test_factura_por_reglas(pdf_factura):
    f = leer_factura(pdf_factura)
    assert f.proveedor.rif == "J-40123456-7"
    assert f.proveedor.nombre == "Ferretería El Tornillo C.A."
    assert f.cliente.rif == "J-29876543-2"
    assert f.numero == "000123"
    assert f.fecha == "2026-10-15"
    assert (f.subtotal, f.iva, f.total) == (1000.0, 160.0, 1160.0)
    assert f.moneda == "VES"
    assert f.avisos == []


def test_openai_sin_clave(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EAXY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API key"):
        proveedores.obtener("openai")


def test_openai_arma_la_peticion(monkeypatch, fotos):
    capturado = {}

    def falso_post(url, cuerpo, cabeceras, timeout=120):
        capturado.update(url=url, cuerpo=cuerpo, cabeceras=cabeceras)
        datos = {"proveedor": {"rif": "J401234567"}, "subtotal": "100", "iva": "16", "total": "116"}
        return {"choices": [{"message": {"content": json.dumps(datos)}}]}

    monkeypatch.setattr(proveedores, "_post", falso_post)
    f = leer_factura(fotos[0], ia="openai", clave="sk-prueba")
    assert f.total == 116.0 and f.proveedor.rif == "J-40123456-7"
    assert capturado["cabeceras"]["Authorization"] == "Bearer sk-prueba"
    assert capturado["cuerpo"]["messages"][1]["content"][1]["type"] == "image_url"


def test_pdf_escaneado_va_como_imagen(fotos, tmp_path):
    escaneado = imagenes_a_pdf(fotos[:1], tmp_path / "escaneado.pdf")
    doc = preparar(escaneado)
    assert doc.texto == "" and doc.pdf and doc.imagenes


# ---------- CLI ----------

def test_cli_factura_csv(pdf_factura, tmp_path, capsys):
    salida = tmp_path / "facturas.csv"
    assert main(["factura", str(pdf_factura), "--csv", str(salida)]) == 0
    contenido = salida.read_text(encoding="utf-8-sig")
    assert "J-40123456-7" in contenido and "1160.0" in contenido


def test_cli_img2pdf(fotos, tmp_path, capsys):
    assert main(["img2pdf", *map(str, fotos), "-o", str(tmp_path / "x.pdf")]) == 0
    assert "PDF creado" in capsys.readouterr().out


# ---------- API (solo si está instalado el extra [api]) ----------

def test_api_salud_y_factura(pdf_factura):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from eaxy.api import app

    c = TestClient(app)
    assert c.get("/salud").json()["estado"] == "ok"
    with open(pdf_factura, "rb") as fh:
        r = c.post("/v1/factura", files={"archivo": ("factura.pdf", fh, "application/pdf")})
    assert r.status_code == 200 and r.json()["total"] == 1160.0
