import io
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import requests
import urllib3

# -- Configuration
EMAIL_SENDER   = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

BASE_URL = "https://saihebro.org"
HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; embalses-report/1.0)", "X-Requested-With": "XMLHttpRequest"}

RESERVOIRS = [
    {
        "name":  "Rialb Embalse",
        "tag":   "E076O82PORCE",
        "label": "% Volumen Embalse Rialb",
        "color": "#800080",
        "cid":   "chart_rialb",
        "url":   "https://saihebro.org/tiempo-real/grafica-senal-E076O82PORCE--volumen-embalse-rialb",
    },
    {
        "name":  "Oliana SAI",
        "tag":   "E062O82PORCE",
        "label": "% Volumen Embalse Oliana",
        "color": "#800080",
        "cid":   "chart_oliana",
        "url":   "https://saihebro.org/tiempo-real/grafica-senal-E062O82PORCE--volumen-embalse-oliana",
    },
]


def fetch_reservoir_data(reservoir):
    tag = reservoir["tag"]
    print(f"--> Fetching data for {reservoir['name']} (tag={tag})")

    # Step 1: get metadata (date range + signal info)
    meta_url = f"{BASE_URL}/api/grafica/getMetaDatosSenalesEstacion?tag={tag}&cambio_periodo=7"
    meta = requests.get(meta_url, headers=HEADERS, verify=False, timeout=30)
    meta.raise_for_status()
    meta_json = meta.json()

    fecha_ini = meta_json["fechaIni"]
    fecha_fin = meta_json["fechaFin"]
    senales   = meta_json["senalesSeleccionadas"]
    tipo_cons = meta_json["tipoConsolidado"]

    # Build metaData for just the percentage signal
    pct_key = f"{tag}|VALOR"
    pct_meta = meta_json["metaData"].get(pct_key)
    if pct_meta is None:
        for k, v in meta_json["metaData"].items():
            if v.get("LS_UNID_ING") == "%":
                pct_key = k
                pct_meta = v
                break

    if pct_meta is None:
        raise ValueError(f"No percentage signal found for {tag}")

    # Step 2: POST to get actual time-series data
    payload = {
        "fechaIni": fecha_ini,
        "fechaFin": fecha_fin,
        "metaData": {pct_key: pct_meta},
        "senalesSeleccionadas": pct_meta["TAG"],
        "tipoConsolidado": tipo_cons,
    }
    data_url = f"{BASE_URL}/api/datos-graficas/obtenerGraficaHistorica"
    resp = requests.post(data_url, json=payload, headers=HEADERS, verify=False, timeout=60)
    resp.raise_for_status()
    data_json = resp.json()

    # Check for API-level errors
    if isinstance(data_json, dict) and "errMessage" in data_json and data_json.get("errNumber", 0) != 0:
        raise RuntimeError(f"API error: {data_json['errMessage']}")

    # Extract time series
    series_data = data_json.get(pct_key, {})
    datos = series_data.get("DATOS", [])
    if not datos:
        raise RuntimeError(f"No DATOS found in response for {pct_key}")

    timestamps = [datetime.fromtimestamp(d[0] / 1000) for d in datos]
    values = [d[1] for d in datos]

    latest_val = values[-1] if values else None
    description = series_data.get("LS_DESCRIPCION", reservoir["label"])

    return {
        "name": reservoir["name"],
        "tag": tag,
        "label": description,
        "color": reservoir["color"],
        "cid": reservoir["cid"],
        "url": reservoir["url"],
        "timestamps": timestamps,
        "values": values,
        "latest": latest_val,
        "fecha_ini": fecha_ini,
        "fecha_fin": fecha_fin,
    }


def make_chart(result):
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(result["timestamps"], result["values"],
            color=result["color"], linewidth=1.5)
    ax.set_title(f"{result['label']}  ({result['fecha_ini']} - {result['fecha_fin']})",
                 fontsize=12, fontweight="bold")
    ax.set_ylabel("%")
    ax.set_ylim(0, 110)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    fig.autofmt_xdate(rotation=45)
    ax.grid(True, alpha=0.3)

    if result["latest"] is not None:
        ax.annotate(f'{result["latest"]:.2f}%',
                    xy=(result["timestamps"][-1], result["latest"]),
                    fontsize=11, fontweight="bold", color=result["color"],
                    xytext=(10, 10), textcoords="offset points")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def trend_arrow(values):
    if len(values) < 2:
        return ""
    diff = values[-1] - values[0]
    if diff > 0.5:
        return "\u2191"
    elif diff < -0.5:
        return "\u2193"
    return "\u2192"


def build_html(results):
    rows = ""
    for r in results:
        arrow = trend_arrow(r["values"])
        rows += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd;"><b>{r['name']}</b></td>
            <td style="padding:8px;border:1px solid #ddd;text-align:center;font-size:20px;">
                {r['latest']:.2f}% {arrow}
            </td>
        </tr>
        <tr>
            <td colspan="2" style="padding:8px;border:1px solid #ddd;text-align:center;">
                <img src="cid:{r['cid']}" style="max-width:100%;" />
            </td>
        </tr>
        """

    html = f"""
    <html><body style="font-family:Arial,sans-serif;">
    <h2>Embalses Rialb &amp; Oliana - Informe Diario</h2>
    <p>Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
    <table style="border-collapse:collapse;width:100%;">
        <tr style="background:#2a7ab5;color:white;">
            <th style="padding:8px;border:1px solid #ddd;">Embalse</th>
            <th style="padding:8px;border:1px solid #ddd;">% Volumen</th>
        </tr>
        {rows}
    </table>
    <p style="font-size:11px;color:#888;">
        Fuente: <a href="https://saihebro.org">SAIH Ebro</a> |
        Generado automaticamente por embalses-report
    </p>
    </body></html>
    """
    return html


def send_email(subject, html, images):
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER
    msg.attach(MIMEText(html, "html"))

    for png_bytes, cid in images:
        img = MIMEImage(png_bytes, _subtype="png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print(f"    Email sent to {EMAIL_RECEIVER}")


def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    print("=== SAIH Ebro Daily Reservoir Report ===")
    results = []

    for reservoir in RESERVOIRS:
        result = fetch_reservoir_data(reservoir)
        result["chart_png"] = make_chart(result)
        results.append(result)

    today_str = datetime.now().strftime("%d/%m/%Y")
    subject = f"Embalses Rialb & Oliana - {today_str}"
    html = build_html(results)
    images = [(r["chart_png"], r["cid"]) for r in results]

    send_email(subject, html, images)
    print("=== Done ===")


if __name__ == "__main__":
    main()
