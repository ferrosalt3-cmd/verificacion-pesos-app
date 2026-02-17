import streamlit as st
import pandas as pd
from datetime import date, datetime
import gspread
from google.oauth2.service_account import Credentials

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
import io


APP_TITLE = "VERIFICACIÓN DE PESOS POR CONTENEDOR"


# ---------- Google Sheets ----------
def get_gsheet_client():
    sa_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)

def append_record_to_sheet(meta: dict, df: pd.DataFrame, promedio: float):
    client = get_gsheet_client()
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    worksheet_name = st.secrets["app"]["worksheet_name"]

    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)

    # Guardado "plano": una fila por registro, pesos concatenados
    pesos = df["PESO"].fillna("").astype(str).tolist()
    row = [
        datetime.now().isoformat(timespec="seconds"),
        meta.get("fecha", ""),
        meta.get("producto", ""),
        meta.get("vehiculo", ""),
        f"{promedio:.2f}" if promedio is not None else "",
        "|".join(pesos),
        meta.get("ejecutado_por", ""),
        meta.get("recibido_por", ""),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


# ---------- PDF ----------
def build_pdf(meta: dict, df: pd.DataFrame, promedio: float) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    margin_x = 1.2 * cm
    y = height - 1.2 * cm

    # Título
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_x, y, APP_TITLE)
    y -= 0.6 * cm

    # Encabezado (Fecha / Producto / Vehículo)
    c.setFont("Helvetica", 10)
    c.drawString(margin_x, y, f"FECHA: {meta.get('fecha','')}")
    c.drawString(margin_x + 7*cm, y, f"PRODUCTO: {meta.get('producto','')}")
    y -= 0.6 * cm
    c.drawString(margin_x, y, f"VEHÍCULO / CONTENEDOR: {meta.get('vehiculo','')}")
    y -= 0.8 * cm

    # Tabla de pesos en 3 bloques (1-40, 41-80, 81-120) como tu hoja
    # Construimos una tabla con 6 columnas: (N, PESO) x3
    data = [["N°", "PESO", "N°", "PESO", "N°", "PESO"]]

    pesos = df["PESO"].tolist()
    # asegurar 120
    if len(pesos) < 120:
        pesos = pesos + [None] * (120 - len(pesos))
    pesos = pesos[:120]

    for i in range(40):
        n1 = i + 1
        n2 = i + 41
        n3 = i + 81

        p1 = "" if pesos[n1-1] is None else str(pesos[n1-1])
        p2 = "" if pesos[n2-1] is None else str(pesos[n2-1])
        p3 = "" if pesos[n3-1] is None else str(pesos[n3-1])

        data.append([str(n1), p1, str(n2), p2, str(n3), p3])

    table = Table(
        data,
        colWidths=[1.0*cm, 2.2*cm, 1.0*cm, 2.2*cm, 1.0*cm, 2.2*cm],
        rowHeights=0.5*cm
    )

    style = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])
    table.setStyle(style)

    # Dibujar tabla
    table_width, table_height = table.wrapOn(c, width - 2*margin_x, y)
    table.drawOn(c, margin_x, y - table_height)
    y = y - table_height - 0.8 * cm

    # Peso promedio
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, y, f"PESO PROMEDIO: {promedio:.2f}" if promedio is not None else "PESO PROMEDIO:")
    y -= 1.0 * cm

    # Firmas
    c.setFont("Helvetica", 10)
    c.drawString(margin_x, y, f"EJECUTADO POR: {meta.get('ejecutado_por','')}")
    c.drawString(margin_x + 9*cm, y, f"RECIBIDO POR: {meta.get('recibido_por','')}")
    y -= 0.8 * cm

    # Línea de firma
    c.line(margin_x, y, margin_x + 7*cm, y)
    c.line(margin_x + 9*cm, y, margin_x + 16*cm, y)

    c.showPage()
    c.save()
    return buffer.getvalue()


# ---------- UI ----------
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
        st.session_state.df_pesos = pd.DataFrame({
            "N°": list(range(1, 121)),
            "PESO": [None] * 120
        })

    st.subheader("Registro de Pesos (1 a 120)")
    edited = st.data_editor(
        st.session_state.df_pesos,
        hide_index=True,
        use_container_width=True,
        column_config={
            "N°": st.column_config.NumberColumn(disabled=True),
            "PESO": st.column_config.NumberColumn(min_value=0.0, step=0.1),
        }
    )
    st.session_state.df_pesos = edited

    # Promedio
    pesos_numeric = pd.to_numeric(edited["PESO"], errors="coerce")
    promedio = pesos_numeric.mean(skipna=True)
    st.info(f"Peso promedio (solo celdas llenas): {promedio:.2f}" if pd.notna(promedio) else "Peso promedio: —")

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

    colx, coly = st.columns([1, 1])
    with colx:
        if st.button("Guardar en Google Sheets", type="primary"):
            try:
                append_record_to_sheet(meta, edited, float(promedio) if pd.notna(promedio) else None)
                st.success("✅ Guardado en Google Sheets.")
            except Exception as e:
                st.error(f"Error guardando en Sheets: {e}")

    with coly:
        pdf_bytes = build_pdf(meta, edited, float(promedio) if pd.notna(promedio) else None)
        filename = f"verificacion_pesos_{meta['fecha']}_{meta['vehiculo'] or 'sin_vehiculo'}.pdf".replace(" ", "_")
        st.download_button(
            "Descargar PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf"
        )


if __name__ == "__main__":
    main()

