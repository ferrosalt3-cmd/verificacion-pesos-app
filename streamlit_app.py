import streamlit as st
import pandas as pd
from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
import io


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
    """Crea encabezados si la hoja está vacía."""
    headers = [
        "timestamp",
        "fecha",
        "producto",
        "vehiculo_contenedor",
        "peso_promedio",
        "pesos_pipe_120",
        "ejecutado_por",
        "recibido_por",
    ]
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(headers)


def append_record_to_sheet(meta: dict, df: pd.DataFrame, promedio: float | None):
    client = get_gsheet_client()
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    worksheet_name = st.secrets["app"]["worksheet_name"]

    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    ensure_headers(ws)

    pesos = pd.to_numeric(df["PESO"], errors="coerce").tolist()

    # Convertimos a texto, manteniendo vacíos
    pesos_str = []
    for p in pesos[:120]:
        if p is None or (isinstance(p, float) and pd.isna(p)):
            pesos_str.append("")
        else:
            # Si quieres enteros, cambia a int(p)
            pesos_str.append(str(p))

    row = [
        datetime.now().isoformat(timespec="seconds"),
        meta.get("fecha", ""),
        meta.get("producto", ""),
        meta.get("vehiculo", ""),
        f"{promedio:.2f}" if promedio is not None else "",
        "|".join(pesos_str),
        meta.get("ejecutado_por", ""),
        meta.get("recibido_por", ""),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


# -------------------- PDF (A4) --------------------
def build_pdf(meta: dict, df: pd.DataFrame, promedio: float | None) -> bytes:
    buffer = io.BytesIO()

    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin_x = 1.0 * cm
    y = height - 1.2 * cm

    # Título
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_x, y, APP_TITLE)
    y -= 0.7 * cm

    # Encabezado (Fecha / Producto / Vehículo)
    c.setFont("Helvetica", 10)
    c.drawString(margin_x, y, f"FECHA: {meta.get('fecha','')}")
    c.drawString(margin_x + 7.5 * cm, y, f"PRODUCTO: {meta.get('producto','')}")
    y -= 0.7 * cm

    c.drawString(margin_x, y, f"VEHÍCULO / CONTENEDOR: {meta.get('vehiculo','')}")
    y -= 0.9 * cm

    # Tabla 1..120 en 3 columnas (1-40, 41-80, 81-120)
    data = [["N°", "PESO", "N°", "PESO", "N°", "PESO"]]

    pesos = pd.to_numeric(df["PESO"], errors="coerce").tolist()
    if len(pesos) < 120:
        pesos = pesos + [None] * (120 - len(pesos))
    pesos = pesos[:120]

    def fmt(p):
        if p is None or (isinstance(p, float) and pd.isna(p)):
            return ""
        return str(p)

    for i in range(40):
        n1 = i + 1
        n2 = i + 41
        n3 = i + 81
        data.append([str(n1), fmt(pesos[n1 - 1]), str(n2), fmt(pesos[n2 - 1]), str(n3), fmt(pesos[n3 - 1])])

    table = Table(
        data,
        colWidths=[0.9 * cm, 2.0 * cm, 0.9 * cm, 2.0 * cm, 0.9 * cm, 2.0 * cm],
        rowHeights=0.48 * cm,
    )

    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    table_width, table_height = table.wrapOn(c, width - 2 * margin_x, y)
    table.drawOn(c, margin_x, y - table_height)
    y = y - table_height - 0.8 * cm

    # Peso promedio
    c.setFont("Helvetica-Bold", 10)
    if promedio is None:
        c.drawString(margin_x, y, "PESO PROMEDIO: ")
    else:
        c.drawString(margin_x, y, f"PESO PROMEDIO: {promedio:.2f}")
    y -= 1.2 * cm

    # Firmas
    c.setFont("Helvetica", 10)
    c.drawString(margin_x, y, f"EJECUTADO POR: {meta.get('ejecutado_por','')}")
    c.drawString(margin_x + 9 * cm, y, f"RECIBIDO POR: {meta.get('recibido_por','')}")
    y -= 0.9 * cm

    c.line(margin_x, y, margin_x + 7.5 * cm, y)
    c.line(margin_x + 9 * cm, y, margin_x + 16.5 * cm, y)

    c.showPage()
    c.save()

    return buffer.getvalue()


# -------------------- App UI --------------------
def main():
    st.set_page_config(page_title="Verificación de Pesos", layout="wide")
    st.title("Verificación de pesos por contenedor")

    # Datos generales
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        fecha = st.date_input("Fecha", value=date.today())
    with col2:
        producto = st.text_input("Producto")
    with col3:
        vehiculo = st.text_input("Vehículo / Contenedor")

    st.divider()

    # Tabla editable de pesos (1..120)
    if "df_pesos" not in st.session_state:
        st.session_state.df_pesos = pd.DataFrame({"N°": list(range(1, 121)), "PESO": [None] * 120})

    st.subheader("Registro de Pesos (1 a 120)")
    edited = st.data_editor(
        st.session_state.df_pesos,
        hide_index=True,
        use_container_width=True,
        column_config={
            "N°": st.column_config.NumberColumn("N°", disabled=True),
            "PESO": st.column_config.NumberColumn("PESO", min_value=0.0, step=0.1),
        },
    )
    st.session_state.df_pesos = edited

    # Promedio
    pesos_numeric = pd.to_numeric(edited["PESO"], errors="coerce")
    promedio = pesos_numeric.mean(skipna=True)
    promedio_out = None if pd.isna(promedio) else float(promedio)
    st.info(f"Peso promedio (solo celdas llenas): {promedio_out:.2f}" if promedio_out is not None else "Peso promedio: —")

    st.divider()

    colA, colB = st.columns(2)
    with colA:
        ejecutado_por = st.text_input("Ejecutado por")
    with colB:
        recibido_por = st.text_input("Recibido por")

    meta = {
        "fecha": str(fecha),
        "producto": producto.strip(),
        "vehiculo": vehiculo.strip(),
        "ejecutado_por": ejecutado_por.strip(),
        "recibido_por": recibido_por.strip(),
    }

    # Botones
    b1, b2, b3 = st.columns([1, 1, 1])

    with b1:
        if st.button("Guardar en Google Sheets", type="primary"):
            # Validación básica
            if not meta["producto"] or not meta["vehiculo"]:
                st.warning("Completa PRODUCTO y VEHÍCULO/CONTENEDOR antes de guardar.")
            else:
                try:
                    append_record_to_sheet(meta, edited, promedio_out)
                    st.success("✅ Guardado en Google Sheets.")
                except Exception as e:
                    st.error(f"Error guardando en Sheets: {e}")

    with b2:
        pdf_bytes = build_pdf(meta, edited, promedio_out)
        filename = f"verificacion_pesos_{meta['fecha']}_{(meta['vehiculo'] or 'sin_vehiculo')}.pdf".replace(" ", "_")
        st.download_button(
            "Descargar PDF (A4)",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
        )

    with b3:
        if st.button("Limpiar formulario"):
            st.session_state.df_pesos = pd.DataFrame({"N°": list(range(1, 121)), "PESO": [None] * 120})
            st.rerun()


if __name__ == "__main__":
    main()
