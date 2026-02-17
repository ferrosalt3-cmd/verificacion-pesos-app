import re
import io
import uuid
import math
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle


APP_TITLE = "VERIFICACIÓN DE PESOS POR CONTENEDOR"


# =========================
# Google Sheets (LISTA)
# =========================
def get_gsheet_client():
    sa_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


SHEET_HEADERS = [
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
]


def ensure_headers(ws):
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(SHEET_HEADERS)


def append_list_rows_to_sheet(meta: dict, pesos: list[float | None]):
    client = get_gsheet_client()
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    worksheet_name = st.secrets["app"]["worksheet_name"]

    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    ensure_headers(ws)

    reg_id = meta.get("registro_id") or str(uuid.uuid4())

    # ✅ HORA LOCAL CORRECTA
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for i, p in enumerate(pesos, start=1):
        if p is None or (isinstance(p, float) and np.isnan(p)):
            continue

        rows.append([
            ts,
            reg_id,
            meta.get("fecha", ""),
            meta.get("producto", ""),
            meta.get("vehiculo", ""),
            meta.get("viaje", ""),
            i,
            float(p),
            meta.get("ejecutado_por", ""),
            meta.get("recibido_por", ""),
        ])

    if not rows:
        raise ValueError("No hay pesos para guardar.")

    ws.append_rows(rows, value_input_option="USER_ENTERED")


# =========================
# Helpers
# =========================
def parse_weight_text(raw: str):
    raw = (raw or "").strip()
    if raw == "":
        return None, "Escribe un peso."

    raw2 = raw.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", raw2):
        return None, "Formato inválido. Ej: 25.158"

    return float(raw2), ""


def compute_promedio(pesos):
    arr = pd.to_numeric(pd.Series(pesos), errors="coerce")
    mean_val = arr.mean(skipna=True)
    if pd.isna(mean_val):
        return None
    return float(mean_val)


def fmt_num(p):
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return ""
    return f"{p:.3f}".rstrip("0").rstrip(".")


def last_valid_weight(pesos, up_to_idx):
    for i in range(min(up_to_idx - 1, len(pesos) - 1), -1, -1):
        p = pesos[i]
        if p is None:
            continue
        if isinstance(p, float) and np.isnan(p):
            continue
        return float(p)
    return None


def pesos_to_df(pesos):
    return pd.DataFrame({
        "N°": list(range(1, len(pesos) + 1)),
        "PESO": pesos,
    })


# =========================
# PDF multipágina
# =========================
def draw_single_page(c, meta, pesos_chunk, promedio):
    width, height = A4

    margin = 1.2 * cm
    content_w = width - 2 * margin

    c.setLineWidth(1.0)
    c.rect(margin, margin, content_w, height - 2 * margin)

    header_h = 2.7 * cm
    c.setLineWidth(0.8)
    c.rect(margin, height - margin - header_h, content_w, header_h)

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(
        margin + content_w / 2,
        height - margin - 0.7 * cm,
        APP_TITLE,
    )

    c.setLineWidth(0.6)
    c.line(
        margin,
        height - margin - 1.25 * cm,
        margin + content_w,
        height - margin - 1.25 * cm,
    )

    c.setFont("Helvetica", 10)
    c.drawString(margin + 0.5 * cm, height - margin - 1.95 * cm,
                 f"FECHA: {meta.get('fecha','')}")
    c.drawString(margin + 7.5 * cm, height - margin - 1.95 * cm,
                 f"PRODUCTO: {meta.get('producto','')}")
    c.drawString(margin + 0.5 * cm, height - margin - 2.35 * cm,
                 f"VEHÍCULO / CONTENEDOR: {meta.get('vehiculo','')}")
    c.drawString(margin + 7.5 * cm, height - margin - 2.35 * cm,
                 f"VIAJE: {meta.get('viaje','')}")

    y = height - margin - header_h - 0.9 * cm

    data = [["N°", "PESO", "N°", "PESO", "N°", "PESO"]]
    pesos_120 = (pesos_chunk + [None] * 120)[:120]

    for i in range(40):
        n1, n2, n3 = i + 1, i + 41, i + 81
        data.append([
            str(n1), fmt_num(pesos_120[n1 - 1]),
            str(n2), fmt_num(pesos_120[n2 - 1]),
            str(n3), fmt_num(pesos_120[n3 - 1]),
        ])

    col_widths = [0.9 * cm, 2.2 * cm] * 3
    table = Table(data, colWidths=col_widths, rowHeights=0.47 * cm)

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))

    tw, th = table.wrapOn(c, content_w, y)
    table.drawOn(c, margin + (content_w - tw) / 2, y - th)


def build_pdf_multi(meta, pesos):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    promedio = compute_promedio(pesos)

    pages = max(1, math.ceil(len(pesos) / 120)) if pesos else 1

    for page in range(pages):
        start = page * 120
        end = start + 120
        chunk = pesos[start:end]
        draw_single_page(c, meta, chunk, promedio)
        if page < pages - 1:
            c.showPage()

    c.save()
    return buffer.getvalue()


# =========================
# STATE
# =========================
def init_state():
    if "pesos" not in st.session_state:
        st.session_state.pesos = []
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    if "peso_txt" not in st.session_state:
        st.session_state.peso_txt = ""
    if "registro_id" not in st.session_state:
        st.session_state.registro_id = str(uuid.uuid4())


# =========================
# CALLBACKS
# =========================
def on_fast_save():
    val, err = parse_weight_text(st.session_state.peso_txt)
    if err:
        st.error(err)
        return

    idx = st.session_state.idx

    if idx == len(st.session_state.pesos):
        st.session_state.pesos.append(val)
    else:
        st.session_state.pesos[idx] = val

    st.session_state.idx += 1
    st.session_state.peso_txt = ""


def on_repeat_last():
    last_w = last_valid_weight(st.session_state.pesos, st.session_state.idx)
    if last_w is None:
        st.error("No hay peso anterior.")
        return

    idx = st.session_state.idx
    if idx == len(st.session_state.pesos):
        st.session_state.pesos.append(last_w)
    else:
        st.session_state.pesos[idx] = last_w

    st.session_state.idx += 1
    st.session_state.peso_txt = ""


def on_clear():
    st.session_state.pesos = []
    st.session_state.idx = 0
    st.session_state.peso_txt = ""
    st.session_state.registro_id = str(uuid.uuid4())


# =========================
# APP
# =========================
def main():
    st.set_page_config(layout="wide")
    init_state()

    st.title("Verificación de pesos por contenedor")

    c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
    with c1:
        fecha = st.date_input("Fecha", value=date.today())
    with c2:
        producto = st.text_input("Producto")
    with c3:
        vehiculo = st.text_input("Vehículo / Contenedor")
    with c4:
        viaje = st.text_input("Viaje")

    st.subheader("Captura rápida")

    colA, colB = st.columns([1, 2])
    with colA:
        st.metric("N° actual", st.session_state.idx + 1)

    with colB:
        with st.form("fast_form"):
            st.text_input("Peso", key="peso_txt", placeholder="Ej: 25.158")
            b1, b2 = st.columns(2)
            with b1:
                st.form_submit_button("Guardar (Enter)", on_click=on_fast_save)
            with b2:
                st.form_submit_button("Repetir último", on_click=on_repeat_last)

    promedio = compute_promedio(st.session_state.pesos)
    st.info(f"Peso promedio: {promedio:.3f}" if promedio else "Peso promedio: —")

    colx, coly, colz = st.columns(3)

    meta = {
        "registro_id": st.session_state.registro_id,
        "fecha": str(fecha),
        "producto": producto,
        "vehiculo": vehiculo,
        "viaje": viaje,
        "ejecutado_por": "",
        "recibido_por": "",
    }

    with colx:
        if st.button("Guardar en Google Sheets"):
            append_list_rows_to_sheet(meta, st.session_state.pesos)
            st.success("Guardado como LISTA.")

    with coly:
        pdf_bytes = build_pdf_multi(meta, st.session_state.pesos)
        st.download_button(
            "Descargar PDF",
            data=pdf_bytes,
            file_name="verificacion_pesos.pdf",
            mime="application/pdf",
        )

    with colz:
        st.button("Limpiar formulario", on_click=on_clear)


if __name__ == "__main__":
    main()
