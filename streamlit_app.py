import re
import io
import uuid
import math
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from datetime import date, datetime
from zoneinfo import ZoneInfo  # ✅ hora Lima

import gspread
from google.oauth2.service_account import Credentials

from PIL import Image
from streamlit_drawable_canvas import st_canvas

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader


APP_TITLE = "VERIFICACIÓN DE PESOS POR CONTENEDOR"


# =========================
# Google Sheets (LISTA)
# =========================
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


def get_gsheet_client():
    sa_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def ensure_headers(ws):
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(SHEET_HEADERS)


def append_list_rows_to_sheet(meta: dict, pesos: list[float | None]):
    """
    Guarda como LISTA: una fila por cada peso.
    """
    client = get_gsheet_client()
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    worksheet_name = st.secrets["app"]["worksheet_name"]

    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    ensure_headers(ws)

    reg_id = meta.get("registro_id") or str(uuid.uuid4())

    # ✅ HORA CORRECTA LIMA
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
def parse_weight_text(raw: str) -> tuple[float | None, str]:
    raw = (raw or "").strip()
    if raw == "":
        return None, "Escribe un peso antes de guardar."
    raw2 = raw.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", raw2):
        return None, "Formato inválido. Ej: 25.158"
    return float(raw2), ""


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


def fit_text(c, text, max_width, base_font="Helvetica", base_size=10, min_size=7):
    size = base_size
    while size >= min_size:
        c.setFont(base_font, size)
        if c.stringWidth(text, base_font, size) <= max_width:
            return base_font, size
        size -= 1
    return base_font, min_size


def last_valid_weight(pesos: list[float | None], up_to_idx: int) -> float | None:
    for i in range(min(up_to_idx - 1, len(pesos) - 1), -1, -1):
        p = pesos[i]
        if p is None:
            continue
        if isinstance(p, float) and np.isnan(p):
            continue
        return float(p)
    return None


def pesos_to_df(pesos):
    return pd.DataFrame({"N°": list(range(1, len(pesos) + 1)), "PESO": pesos})


def df_to_pesos(df: pd.DataFrame):
    return pd.to_numeric(df["PESO"], errors="coerce").tolist()


def draw_signature(c, png_bytes: bytes | None, x, y, w, h):
    """
    Dibuja una firma PNG dentro del rectángulo definido.
    Para que se vea MÁS GRANDE, se dibuja ocupando casi todo el alto/ancho
    del área disponible.
    """
    if not png_bytes:
        return
    try:
        img = ImageReader(io.BytesIO(png_bytes))
        c.drawImage(
            img,
            x,
            y,
            width=w,
            height=h,
            preserveAspectRatio=True,
            mask="auto",
            anchor="c",
        )
    except Exception:
        pass


# =========================
# PDF PRO + MULTIPÁGINA (120 por hoja)
# =========================
def draw_pdf_page(c: canvas.Canvas, meta: dict, pesos_chunk: list[float | None], promedio_global: float | None):
    width, height = A4

    margin = 1.2 * cm
    content_w = width - 2 * margin

    # Marco externo
    c.setLineWidth(1.0)
    c.rect(margin, margin, content_w, height - 2 * margin)

    # Header box
    header_h = 2.7 * cm
    c.setLineWidth(0.8)
    c.rect(margin, height - margin - header_h, content_w, header_h)

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(margin + content_w / 2, height - margin - 0.7 * cm, APP_TITLE)

    c.setLineWidth(0.6)
    c.line(margin, height - margin - 1.25 * cm, margin + content_w, height - margin - 1.25 * cm)

    # Textos header
    c.setFont("Helvetica", 10)
    c.drawString(margin + 0.5 * cm, height - margin - 1.95 * cm, f"FECHA: {meta.get('fecha','')}")
    c.drawString(margin + 7.5 * cm, height - margin - 1.95 * cm, f"PRODUCTO: {meta.get('producto','')}")
    c.drawString(margin + 0.5 * cm, height - margin - 2.35 * cm, f"VEHÍCULO / CONTENEDOR: {meta.get('vehiculo','')}")
    c.drawString(margin + 7.5 * cm, height - margin - 2.35 * cm, f"VIAJE: {meta.get('viaje','')}")

    # Separación entre header y tabla
    y = height - margin - header_h - 0.9 * cm

    # Tabla 120 = 40 filas x 3 bloques
    data = [["N°", "PESO", "N°", "PESO", "N°", "PESO"]]
    pesos_120 = (pesos_chunk + [None] * 120)[:120]

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
    y = y - th - 1.0 * cm

    # Promedio global
    box_h = 1.0 * cm
    c.setLineWidth(0.8)
    c.rect(margin + 0.5 * cm, y - box_h + 0.2 * cm, content_w - 1.0 * cm, box_h)

    c.setFont("Helvetica-Bold", 10)
    prom_txt = f"{promedio_global:.3f}" if promedio_global is not None else ""
    c.drawString(margin + 1.0 * cm, y - 0.45 * cm, f"PESO PROMEDIO: {prom_txt}")

    y -= 1.25 * cm

    # Firmas dentro del marco
    inner_padding = 1.0 * cm
    inner_left = margin + inner_padding
    inner_right = margin + content_w - inner_padding
    inner_width = inner_right - inner_left

    gap = 1.0 * cm
    sig_w = (inner_width - gap) / 2
    sig_h = 1.75 * cm

    min_bottom = margin + 0.35 * cm
    if (y - sig_h) < min_bottom:
        y = min_bottom + sig_h

    left_x = inner_left
    right_x = inner_left + sig_w + gap

    c.setLineWidth(0.8)
    c.rect(left_x, y - sig_h, sig_w, sig_h)
    c.rect(right_x, y - sig_h, sig_w, sig_h)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x + 0.4 * cm, y - 0.55 * cm, "EJECUTADO POR:")
    c.drawString(right_x + 0.4 * cm, y - 0.55 * cm, "RECIBIDO POR:")

    name_left = meta.get("ejecutado_por", "") or ""
    name_right = meta.get("recibido_por", "") or ""

    max_text_w = sig_w - 0.8 * cm
    font_left, size_left = fit_text(c, name_left, max_text_w, base_font="Helvetica", base_size=10, min_size=7)
    font_right, size_right = fit_text(c, name_right, max_text_w, base_font="Helvetica", base_size=10, min_size=7)

    c.setFont(font_left, size_left)
    c.drawString(left_x + 0.4 * cm, y - 1.05 * cm, name_left)

    c.setFont(font_right, size_right)
    c.drawString(right_x + 0.4 * cm, y - 1.05 * cm, name_right)

    # ✅ Firma dentro del cuadro (más grande)
    # Antes: 0.55cm alto. Ahora subimos a ~0.95cm y damos más ancho.
    sig_area_h = 0.95 * cm
    sig_area_y = (y - 1.62 * cm)  # un poco más abajo para que “calce” mejor
    sig_area_x_left = left_x + 0.4 * cm
    sig_area_x_right = right_x + 0.4 * cm
    sig_area_w = sig_w - 0.8 * cm

    draw_signature(c, meta.get("firma_ejecutado_png"), sig_area_x_left, sig_area_y, sig_area_w, sig_area_h)
    draw_signature(c, meta.get("firma_recibido_png"), sig_area_x_right, sig_area_y, sig_area_w, sig_area_h)

    # línea (debajo de la firma)
    c.setLineWidth(0.6)
    c.line(left_x + 0.4 * cm, y - 1.55 * cm, left_x + sig_w - 0.4 * cm, y - 1.55 * cm)
    c.line(right_x + 0.4 * cm, y - 1.55 * cm, right_x + sig_w - 0.4 * cm, y - 1.55 * cm)


def build_pdf_multi(meta: dict, pesos: list[float | None]) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    promedio_global = compute_promedio(pesos)

    total = len(pesos)
    pages = max(1, math.ceil(total / 120)) if total > 0 else 1

    for page in range(pages):
        start = page * 120
        end = start + 120
        chunk = pesos[start:end]
        draw_pdf_page(c, meta, chunk, promedio_global)
        if page < pages - 1:
            c.showPage()

    c.save()
    return buffer.getvalue()


# =========================
# State
# =========================
def init_state():
    if "pesos" not in st.session_state:
        st.session_state.pesos = []
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    if "modo" not in st.session_state:
        st.session_state.modo = "Captura rápida"
    if "peso_txt" not in st.session_state:
        st.session_state.peso_txt = ""
    if "fast_error" not in st.session_state:
        st.session_state.fast_error = ""
    if "fast_info" not in st.session_state:
        st.session_state.fast_info = ""
    if "table_df" not in st.session_state:
        st.session_state.table_df = pesos_to_df(st.session_state.pesos)
    if "registro_id" not in st.session_state:
        st.session_state.registro_id = str(uuid.uuid4())

    if "confirm_clear" not in st.session_state:
        st.session_state.confirm_clear = False

    if "last_saved_payload" not in st.session_state:
        st.session_state.last_saved_payload = None

    if "save_status" not in st.session_state:
        st.session_state.save_status = None
    if "save_message" not in st.session_state:
        st.session_state.save_message = ""

    # ✅ firmas
    if "firma_ejecutado_png" not in st.session_state:
        st.session_state.firma_ejecutado_png = None
    if "firma_recibido_png" not in st.session_state:
        st.session_state.firma_recibido_png = None


# =========================
# Callbacks
# =========================
def clear_save_notice():
    st.session_state.save_status = None
    st.session_state.save_message = ""


def on_fast_save():
    clear_save_notice()
    st.session_state.fast_error = ""
    st.session_state.fast_info = ""

    val, err = parse_weight_text(st.session_state.peso_txt)
    if err:
        st.session_state.fast_error = err
        return

    idx = st.session_state.idx

    if idx == len(st.session_state.pesos):
        st.session_state.pesos.append(float(val))
    elif idx < len(st.session_state.pesos):
        st.session_state.pesos[idx] = float(val)
    else:
        while len(st.session_state.pesos) < idx:
            st.session_state.pesos.append(None)
        st.session_state.pesos.append(float(val))

    st.session_state.idx = idx + 1
    st.session_state.peso_txt = ""
    st.session_state.table_df = pesos_to_df(st.session_state.pesos)


def on_repeat_last():
    clear_save_notice()
    st.session_state.fast_error = ""
    st.session_state.fast_info = ""

    idx = st.session_state.idx
    last_w = last_valid_weight(st.session_state.pesos, idx)
    if last_w is None:
        st.session_state.fast_error = "No hay un peso anterior para repetir."
        return

    if idx == len(st.session_state.pesos):
        st.session_state.pesos.append(float(last_w))
    elif idx < len(st.session_state.pesos):
        st.session_state.pesos[idx] = float(last_w)
    else:
        while len(st.session_state.pesos) < idx:
            st.session_state.pesos.append(None)
        st.session_state.pesos.append(float(last_w))

    st.session_state.idx = idx + 1
    st.session_state.peso_txt = ""
    st.session_state.table_df = pesos_to_df(st.session_state.pesos)


def on_apply_table():
    clear_save_notice()
    df = st.session_state.table_df.copy()
    st.session_state.pesos = df_to_pesos(df)
    st.session_state.idx = min(st.session_state.idx, len(st.session_state.pesos))


def on_clear():
    st.session_state.pesos = []
    st.session_state.idx = 0
    st.session_state.pop("peso_txt", None)
    st.session_state.fast_error = ""
    st.session_state.fast_info = ""
    st.session_state.table_df = pesos_to_df(st.session_state.pesos)
    st.session_state.registro_id = str(uuid.uuid4())
    st.session_state.firma_ejecutado_png = None
    st.session_state.firma_recibido_png = None
    st.session_state.pop("canvas_firma_ejecutado", None)
    st.session_state.pop("canvas_firma_recibido", None)


# =========================
# App
# =========================
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

        colA, colB, colC = st.columns([1, 2, 1])
        with colA:
            st.metric("N° actual", st.session_state.idx + 1)

        with colB:
            with st.form("fast_form", clear_on_submit=False):
                st.text_input("Peso", key="peso_txt", placeholder="Ej: 25.158")
                cbtn1, cbtn2 = st.columns([1, 1])
                with cbtn1:
                    st.form_submit_button("Guardar (Enter)", on_click=on_fast_save)
                with cbtn2:
                    st.form_submit_button("Repetir último", on_click=on_repeat_last)

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
                if st.button("⬆️", help="Anterior", disabled=(st.session_state.idx == 0)):
                    st.session_state.idx = max(0, st.session_state.idx - 1)
                    st.session_state.pop("peso_txt", None)
                    st.session_state.fast_error = ""
                    st.session_state.fast_info = ""
                    st.rerun()
            with b2:
                if st.button("⬇️", help="Siguiente"):
                    st.session_state.idx = st.session_state.idx + 1
                    st.session_state.pop("peso_txt", None)
                    st.session_state.fast_error = ""
                    st.session_state.fast_info = ""
                    st.rerun()

        st.caption("Últimos valores ingresados")
        last_rows = []
        upto = min(len(st.session_state.pesos), st.session_state.idx)
        for i in range(max(0, upto - 10), upto):
            last_rows.append({"N°": i + 1, "PESO": st.session_state.pesos[i]})
        if last_rows:
            st.dataframe(pd.DataFrame(last_rows), use_container_width=True, hide_index=True)
        else:
            st.write("Aún no hay registros.")

    else:
        st.subheader("Tabla (revisión/edición)")

        st.session_state.table_df = st.data_editor(
            pesos_to_df(st.session_state.pesos),
            key="table_editor",
            hide_index=True,
            use_container_width=True,
            column_config={
                "N°": st.column_config.NumberColumn("N°", disabled=True),
                "PESO": st.column_config.NumberColumn("PESO", min_value=0.0, step=0.001, format="%.3f"),
            },
        )

        st.button("Aplicar cambios de tabla", on_click=on_apply_table)
        st.caption("Consejo: para capturar rápido con Enter, usa “Captura rápida”.")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        ejecutado_por = st.text_input("Ejecutado por")
    with col2:
        recibido_por = st.text_input("Recibido por")

    # ✅ Firmas (dibujar)
    st.subheader("Firmas")
    f1, f2 = st.columns(2)

    with f1:
        st.caption("Firma Ejecutado")
        canvas_e = st_canvas(
            fill_color="rgba(255, 255, 255, 0)",
            stroke_width=3,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=180,
            width=420,
            drawing_mode="freedraw",
            key="canvas_firma_ejecutado",
        )
        if canvas_e.image_data is not None:
            img = Image.fromarray(canvas_e.image_data.astype("uint8"))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            st.session_state.firma_ejecutado_png = buf.getvalue()

        if st.button("Borrar firma Ejecutado"):
            st.session_state.firma_ejecutado_png = None
            st.session_state.pop("canvas_firma_ejecutado", None)
            st.rerun()

    with f2:
        st.caption("Firma Recibido")
        canvas_r = st_canvas(
            fill_color="rgba(255, 255, 255, 0)",
            stroke_width=3,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=180,
            width=420,
            drawing_mode="freedraw",
            key="canvas_firma_recibido",
        )
        if canvas_r.image_data is not None:
            img = Image.fromarray(canvas_r.image_data.astype("uint8"))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            st.session_state.firma_recibido_png = buf.getvalue()

        if st.button("Borrar firma Recibido"):
            st.session_state.firma_recibido_png = None
            st.session_state.pop("canvas_firma_recibido", None)
            st.rerun()

    st.divider()

    meta = {
        "registro_id": st.session_state.registro_id,
        "fecha": str(fecha),
        "producto": producto.strip(),
        "vehiculo": vehiculo.strip(),
        "viaje": viaje.strip(),
        "ejecutado_por": ejecutado_por.strip(),
        "recibido_por": recibido_por.strip(),
        "firma_ejecutado_png": st.session_state.firma_ejecutado_png,
        "firma_recibido_png": st.session_state.firma_recibido_png,
    }

    if st.session_state.save_status == "ok":
        st.success(st.session_state.save_message)
    elif st.session_state.save_status == "error":
        st.error(st.session_state.save_message)

    b1, b2, b3 = st.columns([1, 1, 1])

    with b1:
        if st.button("Guardar en Google Sheets", type="primary"):
            if not meta["producto"] or not meta["vehiculo"]:
                st.session_state.save_status = "error"
                st.session_state.save_message = "Completa PRODUCTO y VEHÍCULO/CONTENEDOR antes de guardar."
                st.rerun()
            else:
                try:
                    append_list_rows_to_sheet(meta, st.session_state.pesos)

                    st.session_state.last_saved_payload = {
                        "meta": meta,
                        "pesos": st.session_state.pesos.copy(),
                    }

                    st.session_state.save_status = "ok"
                    st.session_state.save_message = (
                        "✅ Guardado exitosamente en Google Sheets. "
                        "Ahora puedes descargar el PDF con el botón “Descargar PDF (A4)”."
                    )

                    on_clear()
                    st.rerun()
                except Exception as e:
                    st.session_state.save_status = "error"
                    st.session_state.save_message = f"❌ Error guardando en Sheets: {e}"
                    st.rerun()

    with b2:
        pesos_para_pdf = st.session_state.pesos
        meta_para_pdf = meta
        usando_ultimo = False

        if (not pesos_para_pdf) and st.session_state.last_saved_payload:
            meta_para_pdf = st.session_state.last_saved_payload["meta"]
            pesos_para_pdf = st.session_state.last_saved_payload["pesos"]
            usando_ultimo = True

        if not pesos_para_pdf and not st.session_state.last_saved_payload:
            st.info("No hay datos para PDF todavía.")
            pdf_bytes = build_pdf_multi(meta_para_pdf, [])
        else:
            pdf_bytes = build_pdf_multi(meta_para_pdf, pesos_para_pdf)

        filename = f"verificacion_pesos_{meta_para_pdf['fecha']}_{(meta_para_pdf['vehiculo'] or 'sin_vehiculo')}.pdf".replace(" ", "_")
        st.download_button("Descargar PDF (A4)", data=pdf_bytes, file_name=filename, mime="application/pdf")

        if usando_ultimo:
            st.info("ℹ️ Este PDF corresponde al ÚLTIMO registro guardado en Google Sheets (aunque la pantalla se haya limpiado).")

    with b3:
        if st.button("Limpiar formulario"):
            st.session_state.confirm_clear = True

        if st.session_state.confirm_clear:
            st.warning("¿Seguro que deseas limpiar? Se perderán datos NO guardados.")
            cc1, cc2 = st.columns(2)
            if cc1.button("Sí, limpiar"):
                st.session_state.confirm_clear = False
                on_clear()
                clear_save_notice()
                st.rerun()
            if cc2.button("No"):
                st.session_state.confirm_clear = False


if __name__ == "__main__":
    main()
