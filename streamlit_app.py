import re
import io
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


# -------------------- Google Sheets --------------------
def get_gsheet_client():
    sa_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def ensure_headers(ws):
    headers = [
        "timestamp",
        "fecha",
        "producto",
        "vehiculo_contenedor",
        "viaje",
        "peso_promedio",
        "pesos_pipe_120",
        "ejecutado_por",
        "recibido_por",
    ]
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(headers)
    else:
        # Si ya existen headers antiguos, no forzamos cambios (evita romper hojas en producción)
        pass


def append_record_to_sheet(meta: dict, pesos: list[float | None], promedio: float | None):
    client = get_gsheet_client()
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    worksheet_name = st.secrets["app"]["worksheet_name"]

    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    ensure_headers(ws)

    pesos_str = []
    for p in (pesos[:120] + [None] * 120)[:120]:
        if p is None or (isinstance(p, float) and np.isnan(p)):
            pesos_str.append("")
        else:
            pesos_str.append(str(p))

    row = [
        datetime.now().isoformat(timespec="seconds"),
        meta.get("fecha", ""),
        meta.get("producto", ""),
        meta.get("vehiculo", ""),
        meta.get("viaje", ""),
        f"{promedio:.3f}" if promedio is not None else "",
        "|".join(pesos_str),
        meta.get("ejecutado_por", ""),
        meta.get("recibido_por", ""),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


# -------------------- Helpers --------------------
def compute_promedio(pesos: list[float | None]) -> float | None:
    arr = pd.to_numeric(pd.Series(pesos), errors="coerce")
    mean_val = arr.mean(skipna=True)
    if pd.isna(mean_val):
        return None
    return float(mean_val)


def fmt_num(p: float | None) -> str:
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return ""
    return f"{p:.3f}".rstrip("0").rstrip(".")


def pesos_to_df(pesos):
    return pd.DataFrame({"N°": list(range(1, 121)), "PESO": pesos})


def df_to_pesos(df: pd.DataFrame):
    return pd.to_numeric(df["PESO"], errors="coerce").tolist()


# -------------------- PDF (A4 profesional) --------------------
def build_pdf(meta: dict, pesos: list[float | None], promedio: float | None) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin = 1.2 * cm
    content_w = width - 2 * margin

    # Marco externo
    c.setLineWidth(1.0)
    c.rect(margin, margin, content_w, height - 2 * margin)

    # Header box
    header_h = 2.7 * cm  # un poquito más alto para separación
    c.setLineWidth(0.8)
    c.rect(margin, height - margin - header_h, content_w, header_h)

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(margin + content_w / 2, height - margin - 0.7 * cm, APP_TITLE)

    # Línea separadora dentro del header (un poco más abajo)
    c.setLineWidth(0.6)
    c.line(margin, height - margin - 1.25 * cm, margin + content_w, height - margin - 1.25 * cm)

    # Textos header con más “aire”
    c.setFont("Helvetica", 10)
    c.drawString(margin + 0.5 * cm, height - margin - 1.95 * cm, f"FECHA: {meta.get('fecha','')}")
    c.drawString(margin + 7.5 * cm, height - margin - 1.95 * cm, f"PRODUCTO: {meta.get('producto','')}")
    c.drawString(margin + 0.5 * cm, height - margin - 2.35 * cm, f"VEHÍCULO / CONTENEDOR: {meta.get('vehiculo','')}")
    c.drawString(margin + 7.5 * cm, height - margin - 2.35 * cm, f"VIAJE: {meta.get('viaje','')}")

    # Más separación entre header y tabla
    y = height - margin - header_h - 0.9 * cm

    # Tabla 3 bloques
    data = [["N°", "PESO", "N°", "PESO", "N°", "PESO"]]
    pesos_120 = (pesos[:120] + [None] * 120)[:120]

    for i in range(40):
        n1, n2, n3 = i + 1, i + 41, i + 81
        data.append([
            str(n1), fmt_num(pesos_120[n1 - 1]),
            str(n2), fmt_num(pesos_120[n2 - 1]),
            str(n3), fmt_num(pesos_120[n3 - 1]),
        ])

    col_widths = [0.9 * cm, 2.2 * cm, 0.9 * cm, 2.2 * cm, 0.9 * cm, 2.2 * cm]
    row_h = 0.47 * cm
    table = Table(data, colWidths=col_widths, rowHeights=row_h)

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 1.0, colors.black),
    ]))

    tw, th = table.wrapOn(c, content_w, y)
    table_x = margin + (content_w - tw) / 2
    table.drawOn(c, table_x, y - th)
    y = y - th - 1.1 * cm  # un poco más de separación

    # Promedio
    box_h = 1.0 * cm
    c.setLineWidth(0.8)
    c.rect(margin + 0.5 * cm, y - box_h + 0.2 * cm, content_w - 1.0 * cm, box_h)

    c.setFont("Helvetica-Bold", 10)
    prom_txt = f"{promedio:.3f}" if promedio is not None else ""
    c.drawString(margin + 1.0 * cm, y - 0.45 * cm, f"PESO PROMEDIO: {prom_txt}")
    y -= 1.7 * cm  # más aire

    # Firmas
    sig_w = (content_w - 2.0 * cm) / 2
    sig_h = 2.0 * cm
    left_x = margin + 0.5 * cm
    right_x = left_x + sig_w + 1.0 * cm

    c.setLineWidth(0.8)
    c.rect(left_x, y - sig_h, sig_w, sig_h)
    c.rect(right_x, y - sig_h, sig_w, sig_h)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x + 0.4 * cm, y - 0.6 * cm, "EJECUTADO POR:")
    c.drawString(right_x + 0.4 * cm, y - 0.6 * cm, "RECIBIDO POR:")

    c.setFont("Helvetica", 10)
    c.drawString(left_x + 0.4 * cm, y - 1.2 * cm, meta.get("ejecutado_por", ""))
    c.drawString(right_x + 0.4 * cm, y - 1.2 * cm, meta.get("recibido_por", ""))

    c.setLineWidth(0.6)
    c.line(left_x + 0.4 * cm, y - 1.7 * cm, left_x + sig_w - 0.4 * cm, y - 1.7 * cm)
    c.line(right_x + 0.4 * cm, y - 1.7 * cm, right_x + sig_w - 0.4 * cm, y - 1.7 * cm)

    c.showPage()
    c.save()
    return buffer.getvalue()


# -------------------- State --------------------
def init_state():
    if "pesos" not in st.session_state:
        st.session_state.pesos = [None] * 120
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    if "modo" not in st.session_state:
        st.session_state.modo = "Captura rápida"
    if "peso_txt" not in st.session_state:
        st.session_state.peso_txt = ""
    if "fast_error" not in st.session_state:
        st.session_state.fast_error = ""
    if "table_df" not in st.session_state:
        st.session_state.table_df = pesos_to_df(st.session_state.pesos)


# -------------------- Callbacks --------------------
def on_fast_save():
    st.session_state.fast_error = ""
    idx = st.session_state.idx
    raw = (st.session_state.peso_txt or "").strip()

    if raw == "":
        st.session_state.fast_error = "Escribe un peso antes de guardar."
        return

    raw2 = raw.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", raw2):
        st.session_state.fast_error = "Formato inválido. Ej: 25.158"
        return

    val = float(raw2)
    st.session_state.pesos[idx] = val

    if st.session_state.idx < 119:
        st.session_state.idx += 1

    st.session_state.peso_txt = ""
    st.session_state.table_df = pesos_to_df(st.session_state.pesos)


def on_apply_table():
    df = st.session_state.table_df.copy()
    st.session_state.pesos = df_to_pesos(df)


# -------------------- App --------------------
def main():
    st.set_page_config(page_title="Verificación de Pesos", layout="wide")
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

    st.divider()

    st.session_state.modo = st.radio(
        "Modo de captura",
        ["Captura rápida", "Tabla (revisión/edición)"],
        horizontal=True,
    )

    promedio = compute_promedio(st.session_state.pesos)
    st.info(f"Peso promedio: {promedio:.3f}" if promedio is not None else "Peso promedio: —")

    st.divider()

    if st.session_state.modo == "Captura rápida":
        st.subheader("Captura rápida (escribe el peso y presiona Enter)")

        idx = st.session_state.idx
        n_actual = idx + 1

        colA, colB, colC = st.columns([1, 2, 1])
        with colA:
            st.metric("N° actual", n_actual)

        with colB:
            with st.form("fast_form", clear_on_submit=False):
                st.text_input("Peso", key="peso_txt", placeholder="Ej: 25.158")
                st.form_submit_button("Guardar (Enter)", on_click=on_fast_save)

            components.html(
                """
                <script>
                  const inputs = window.parent.document.querySelectorAll('input[type="text"]');
                  for (const i of inputs) {
                    const aria = i.getAttribute('aria-label') || '';
                    if (aria.trim() === 'Peso') {
                      i.setAttribute('inputmode', 'decimal');
                      i.setAttribute('pattern', '[0-9]*[\\.,]?[0-9]*');
                      i.focus();
                      i.select();
                    }
                  }
                </script>
                """,
                height=0,
            )

            if st.session_state.fast_error:
                st.error(st.session_state.fast_error)

        with colC:
            b1, b2 = st.columns(2)
            with b1:
                if st.button("⬆️", help="Anterior"):
                    st.session_state.idx = max(0, st.session_state.idx - 1)
                    st.session_state.peso_txt = ""
                    st.session_state.fast_error = ""
                    st.rerun()
            with b2:
                if st.button("⬇️", help="Siguiente"):
                    st.session_state.idx = min(119, st.session_state.idx + 1)
                    st.session_state.peso_txt = ""
                    st.session_state.fast_error = ""
                    st.rerun()

        st.caption("Últimos valores ingresados")
        last_rows = []
        for i in range(max(0, st.session_state.idx - 10), st.session_state.idx):
            last_rows.append({"N°": i + 1, "PESO": st.session_state.pesos[i]})
        if last_rows:
            st.dataframe(pd.DataFrame(last_rows), use_container_width=True, hide_index=True)

    else:
        st.subheader("Tabla (revisión/edición)")

        st.session_state.table_df = st.data_editor(
            st.session_state.table_df,
            key="table_editor",
            hide_index=True,
            use_container_width=True,
            column_config={
                "N°": st.column_config.NumberColumn("N°", disabled=True),
                "PESO": st.column_config.NumberColumn("PESO", min_value=0.0, step=0.001, format="%.3f"),
            },
        )

        colx, coly = st.columns([1, 3])
        with colx:
            st.button("Aplicar cambios de tabla", on_click=on_apply_table)
        with coly:
            st.caption("Consejo: para Enter → siguiente, usa “Captura rápida”.")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        ejecutado_por = st.text_input("Ejecutado por")
    with col2:
        recibido_por = st.text_input("Recibido por")

    meta = {
        "fecha": str(fecha),
        "producto": producto.strip(),
        "vehiculo": vehiculo.strip(),
        "viaje": viaje.strip(),
        "ejecutado_por": ejecutado_por.strip(),
        "recibido_por": recibido_por.strip(),
    }

    b1, b2, b3 = st.columns([1, 1, 1])

    with b1:
        if st.button("Guardar en Google Sheets", type="primary"):
            if not meta["producto"] or not meta["vehiculo"]:
                st.warning("Completa PRODUCTO y VEHÍCULO/CONTENEDOR antes de guardar.")
            else:
                try:
                    promedio_now = compute_promedio(st.session_state.pesos)
                    append_record_to_sheet(meta, st.session_state.pesos, promedio_now)
                    st.success("✅ Guardado en Google Sheets.")
                except Exception as e:
                    st.error(f"Error guardando en Sheets: {e}")

    with b2:
        promedio_now = compute_promedio(st.session_state.pesos)
        pdf_bytes = build_pdf(meta, st.session_state.pesos, promedio_now)
        filename = f"verificacion_pesos_{meta['fecha']}_{(meta['vehiculo'] or 'sin_vehiculo')}.pdf".replace(" ", "_")
        st.download_button("Descargar PDF (A4)", data=pdf_bytes, file_name=filename, mime="application/pdf")

    with b3:
        if st.button("Limpiar formulario"):
            st.session_state.pesos = [None] * 120
            st.session_state.idx = 0
            st.session_state.peso_txt = ""
            st.session_state.fast_error = ""
            st.session_state.table_df = pesos_to_df(st.session_state.pesos)
            st.rerun()


if __name__ == "__main__":
    main()
