import streamlit as st
import pandas as pd
import numpy as np
import uuid
import io
from datetime import date, datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.lib import colors


# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Verificación de Pesos", layout="wide")


# =========================================================
# GOOGLE SHEETS
# =========================================================
def get_gsheet_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def ensure_headers(ws):
    headers = ws.row_values(1)
    if headers:
        return

    ws.append_row([
        "timestamp",
        "registro_id",
        "fecha",
        "producto",
        "vehiculo_contenedor",
        "viaje",
        "n",
        "peso",
        "ejecutado_por",
        "recibido_por",
    ])


def append_list_rows_to_sheet(meta, pesos):
    client = get_gsheet_client()
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    worksheet_name = st.secrets["app"]["worksheet_name"]

    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    ensure_headers(ws)

    reg_id = meta.get("registro_id") or str(uuid.uuid4())

    # ✅ HORA CORRECTA PERÚ (LIMA)
    ts = datetime.now(ZoneInfo("America/Lima")).strftime("%Y-%m-%d %H:%M:%S")

    rows = []

    for i, p in enumerate(pesos, start=1):
        if p is None or (isinstance(p, float) and np.isnan(p)):
            continue

        rows.append([
            ts,
            reg_id,
            meta.get("fecha", ""),
            meta.get("producto", ""),
            meta.get("vehiculo_contenedor", ""),
            meta.get("viaje", ""),
            i,
            float(p),
            meta.get("ejecutado_por", ""),
            meta.get("recibido_por", ""),
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


# =========================================================
# PDF
# =========================================================
def build_pdf(meta, pesos):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pesos = [p for p in pesos if p not in (None, "")]

    # dividir en páginas de 120
    pages = [pesos[i:i + 120] for i in range(0, len(pesos), 120)]
    if not pages:
        pages = [[]]

    for page_index, page_data in enumerate(pages):
        margin = 1.5 * cm
        content_w = width - 2 * margin

        # marco
        c.setLineWidth(1)
        c.rect(margin, margin, content_w, height - 2 * margin)

        # título
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, height - margin - 0.7 * cm,
                            "VERIFICACIÓN DE PESOS POR CONTENEDOR")

        # info
        c.setFont("Helvetica", 9)
        y_info = height - margin - 1.6 * cm

        c.drawString(margin + 0.4 * cm, y_info,
                     f"FECHA: {meta.get('fecha','')}")
        c.drawString(width / 2, y_info,
                     f"PRODUCTO: {meta.get('producto','')}")

        y_info -= 0.5 * cm

        c.drawString(margin + 0.4 * cm, y_info,
                     f"VEHÍCULO / CONTENEDOR: {meta.get('vehiculo_contenedor','')}")
        c.drawString(width / 2, y_info,
                     f"VIAJE: {meta.get('viaje','')}")

        # ---------------- TABLA ----------------
        start_y = y_info - 1.0 * cm

        data = [["N°", "PESO", "N°", "PESO", "N°", "PESO"]]

        for i in range(40):
            row = []
            for block in range(3):
                idx = i + block * 40
                if idx < len(page_data):
                    val = page_data[idx]
                    row += [idx + 1, f"{val:.3f}"]
                else:
                    row += ["", ""]
            data.append(row)

        table = Table(
            data,
            colWidths=[1 * cm, 2 * cm] * 3,
            rowHeights=0.45 * cm,
        )

        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))

        table.wrapOn(c, width, height)
        table.drawOn(c, margin + 2.5 * cm, start_y - 18 * cm)

        # promedio
        if page_data:
            prom = sum(page_data) / len(page_data)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin + 0.5 * cm, margin + 4.5 * cm,
                         f"PESO PROMEDIO: {prom:.3f}")

        # firmas
        sig_y = margin + 2.8 * cm
        sig_w = 7 * cm
        gap = 2 * cm

        left_x = margin + 2 * cm
        right_x = left_x + sig_w + gap

        c.rect(left_x, sig_y, sig_w, 2 * cm)
        c.rect(right_x, sig_y, sig_w, 2 * cm)

        c.setFont("Helvetica-Bold", 8)
        c.drawString(left_x + 0.3 * cm, sig_y + 1.5 * cm, "EJECUTADO POR:")
        c.drawString(right_x + 0.3 * cm, sig_y + 1.5 * cm, "RECIBIDO POR:")

        c.setFont("Helvetica", 9)
        c.drawString(left_x + 0.3 * cm, sig_y + 0.7 * cm,
                     meta.get("ejecutado_por", ""))
        c.drawString(right_x + 0.3 * cm, sig_y + 0.7 * cm,
                     meta.get("recibido_por", ""))

        if page_index < len(pages) - 1:
            c.showPage()

    c.save()
    buffer.seek(0)
    return buffer


# =========================================================
# SESSION STATE
# =========================================================
if "pesos" not in st.session_state:
    st.session_state.pesos = []

if "peso_txt" not in st.session_state:
    st.session_state.peso_txt = ""


# =========================================================
# UI
# =========================================================
st.title("Verificación de pesos por contenedor")

col1, col2, col3, col4 = st.columns(4)

fecha = col1.date_input("Fecha", value=date.today())
producto = col2.text_input("Producto")
vehiculo = col3.text_input("Vehículo / Contenedor")
viaje = col4.text_input("Viaje")

st.subheader("Captura rápida")

st.write(f"**N° actual:** {len(st.session_state.pesos) + 1}")

with st.form("captura_form", clear_on_submit=True):
    peso_txt = st.text_input(
        "Peso",
        key="peso_txt",
        placeholder="Ej: 25.158"
    )

    c1, c2 = st.columns([1, 1])
    guardar = c1.form_submit_button("Guardar (Enter)")
    repetir = c2.form_submit_button("Repetir último")

    if guardar and peso_txt:
        try:
            val = float(peso_txt.replace(",", "."))
            st.session_state.pesos.append(val)
        except:
            st.error("Peso inválido")

    if repetir and st.session_state.pesos:
        st.session_state.pesos.append(st.session_state.pesos[-1])

# promedio
if st.session_state.pesos:
    prom = sum(st.session_state.pesos) / len(st.session_state.pesos)
    st.info(f"Peso promedio: {prom:.3f}")

st.divider()

# botones
c1, c2, c3 = st.columns(3)

if c1.button("Guardar en Google Sheets"):
    meta = dict(
        fecha=str(fecha),
        producto=producto,
        vehiculo_contenedor=vehiculo,
        viaje=viaje,
        ejecutado_por=st.session_state.get("ejecutado_por", ""),
        recibido_por=st.session_state.get("recibido_por", ""),
    )
    append_list_rows_to_sheet(meta, st.session_state.pesos)
    st.success("Guardado en Google Sheets")

pdf_buffer = build_pdf(
    dict(
        fecha=str(fecha),
        producto=producto,
        vehiculo_contenedor=vehiculo,
        viaje=viaje,
        ejecutado_por=st.session_state.get("ejecutado_por", ""),
        recibido_por=st.session_state.get("recibido_por", ""),
    ),
    st.session_state.pesos,
)

c2.download_button(
    "Descargar PDF",
    pdf_buffer,
    file_name="verificacion_pesos.pdf",
    mime="application/pdf",
)

if c3.button("Limpiar formulario"):
    st.session_state.pesos = []
    st.rerun()
