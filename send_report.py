import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import urllib3

# -- Configuration
EMAIL_SENDER   = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

BASE_URL = "https://saihebro.org"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://saihebro.org/",
    "Origin": "https://saihebro.org",
    "Connection": "keep-alive",
}

RESERVOIRS = [
    {
        "name": "Rialb Embalse",
        "tag": "E076O82PORCE",
        "label": "% Volumen Embalse Rialb",
        "url": "https://saihebro.org/tiempo-real/grafica-senal-E076O82PORCE--volumen-embalse-rialb",
    },
    {
        "name": "Oliana SAI",
        "tag": "E062O82PORCE",
        "label": "% Volumen Embalse Oliana",
        "url": "https://saihebro.org/tiempo-real/grafica-senal-E062O82PORCE--volumen-embalse-oliana",
    },
]

# -- SAIH Cantábrico Configuration
SAIH_CANTABRICO_URL = "https://visor.saichcantabrico.es/wp-admin/admin-ajax.php"
SAIH_CANTABRICO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://visor.saichcantabrico.es/",
    "Origin": "https://visor.saichcantabrico.es",
}

LA_COHILLA = {
    "name": "La Cohilla",
    "codigo": "1253",
    "label": "% Llenado Embalse La Cohilla",
    "url": "https://visor.saichcantabrico.es/",
}

def fetch_reservoir_info(reservoir):
    tag = reservoir["tag"]
    print(f"--> Fetching info for {reservoir['name']} (tag={tag})")

    session = requests.Session()
    session.headers.update(HEADERS)
    session.verify = False

    # Establish session (get cookies like a browser)
    session.get(reservoir["url"], timeout=30)

    # Get metadata (date range + signal descriptions)
    meta_url = f"{BASE_URL}/api/grafica/getMetaDatosSenalesEstacion?tag={tag}&cambio_periodo=7"
    meta = session.get(meta_url, timeout=30)
    meta.raise_for_status()
    meta_json = meta.json()

    fecha_ini = meta_json["fechaIni"]
    fecha_fin = meta_json["fechaFin"]

    # Find the percentage signal metadata
    pct_key = f"{tag}|VALOR"
    pct_meta = meta_json["metaData"].get(pct_key)
    if pct_meta is None:
        for k, v in meta_json["metaData"].items():
            if v.get("LS_UNID_ING") == "%":
                pct_key = k
                pct_meta = v
                break

    # Try to get actual data via POST (may fail from cloud IPs)
    latest_val = None
    try:
        if pct_meta is not None:
            payload = {
                "fechaIni": fecha_ini,
                "fechaFin": fecha_fin,
                "metaData": {pct_key: pct_meta},
                "senalesSeleccionadas": [pct_meta["TAG"]],
                "tipoConsolidado": meta_json["tipoConsolidado"],
            }
            data_url = f"{BASE_URL}/api/datos-graficas/obtenerGraficaHistorica"
            resp = session.post(data_url, json=payload, timeout=60)
            print("STATUS:", resp.status_code)
            print("HEADERS:", resp.headers)
            print("BODY:", resp.text[:1000])  # first 1000 chars

            if resp.status_code == 200:
                data_json = resp.json()
                if pct_key in data_json:
                    datos = data_json[pct_key].get("DATOS", [])
                    if datos:
                        latest_val = datos[-1][1]
                        print(f"    Got value from API: {latest_val}%")
            else:
                print(f"    POST returned {resp.status_code} (expected from cloud IPs)")
    except Exception as e:
        print(f"    POST failed: {e}")

    return {
        "name": reservoir["name"],
        "tag": tag,
        "label": pct_meta["DESCRIPCION"] if pct_meta else reservoir["label"],
        "url": reservoir["url"],
        "fecha_ini": fecha_ini,
        "fecha_fin": fecha_fin,
        "latest": latest_val,
    }

def fetch_la_cohilla_info():
    """Fetch La Cohilla reservoir data from SAIH Cantábrico."""
    print("--> Fetching info for La Cohilla (código=1253)")

    session = requests.Session()
    session.headers.update(SAIH_CANTABRICO_HEADERS)
    session.verify = False

    latest_val = None
    try:
        resp = session.post(
            SAIH_CANTABRICO_URL,
            data={"action": "peticion_cincominutal", "tipo": "embalses"},
            timeout=30,
        )
        resp.raise_for_status()
        json_data = resp.json()

        if json_data.get("success"):
            features = json_data["data"]["features"]
            for feature in features:
                props = feature["properties"]
                if props.get("codigo_general") == LA_COHILLA["codigo"]:
                    latest_val = props.get("porcentaje_llenado")
                    print(f"    Got value from API: {latest_val}%")
                    break
            else:
                print("    Station 1253 not found in response")
        else:
            print("    API returned success=false")
    except Exception as e:
        print(f"    Failed to fetch La Cohilla data: {e}")

    return {
        "name": LA_COHILLA["name"],
        "tag": LA_COHILLA["codigo"],
        "label": LA_COHILLA["label"],
        "url": LA_COHILLA["url"],
        "fecha_ini": None,
        "fecha_fin": None,
        "latest": latest_val,
    }

def build_html(results):
    today_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = ""
    for r in results:
        if r["latest"] is not None:
            val_display = f'<span style="font-size:24px;font-weight:bold;color:#2a7ab5;">{r["latest"]:.2f}%</span>'
        else:
            val_display = '<span style="color:#888;">Ver en SAIH</span>'

        rows += f"""
        <tr>
            <td style="padding:12px;border:1px solid #ddd;">
                <b>{r['name']}</b><br>
                <span style="font-size:12px;color:#666;">{r['label']}</span>
            </td>
            <td style="padding:12px;border:1px solid #ddd;text-align:center;">
                {val_display}
            </td>
            <td style="padding:12px;border:1px solid #ddd;text-align:center;">
                <a href="{r['url']}" style="color:#2a7ab5;text-decoration:none;font-weight:bold;">
                    Ver grafica &#8599;
                </a>
            </td>
        </tr>
        """

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
    <div style="background:#2a7ab5;color:white;padding:15px;text-align:center;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">Embalses Rialb, Oliana &amp; La Cohilla</h2>
        <p style="margin:5px 0 0 0;font-size:14px;">Informe Diario - {today_str}</p>
    </div>
    <table style="border-collapse:collapse;width:100%;margin-top:0;">
        <tr style="background:#f0f0f0;">
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Embalse</th>
            <th style="padding:10px;border:1px solid #ddd;">% Volumen</th>
            <th style="padding:10px;border:1px solid #ddd;">Enlace</th>
        </tr>
        {rows}
    </table>
    <div style="padding:15px;background:#f9f9f9;border-radius:0 0 8px 8px;border:1px solid #ddd;border-top:0;">
        <p style="font-size:12px;color:#888;margin:0;">
            Fuente: <a href="https://saihebro.org" style="color:#2a7ab5;">SAIH Ebro</a>
            | <a href="https://visor.saichcantabrico.es" style="color:#2a7ab5;">SAIH Cantábrico</a><br>
            Generado automaticamente por
            <a href="https://github.com/mauromiranda-14/embalses-report" style="color:#2a7ab5;">embalses-report</a>
        </p>
    </div>
    </body></html>
    """
    return html

def send_email(subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print(f"    Email sent to {EMAIL_RECEIVER}")


def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    print("=== SAIH Ebro & Cantábrico Daily Reservoir Report ===")

    results = []
    for reservoir in RESERVOIRS:
        info = fetch_reservoir_info(reservoir)
        results.append(info)

    # Fetch La Cohilla from SAIH Cantábrico
    cohilla_info = fetch_la_cohilla_info()
    results.append(cohilla_info)

    today_str = datetime.now().strftime("%d/%m/%Y")
    subject = f"Embalses Rialb, Oliana & La Cohilla - {today_str}"
    html = build_html(results)
    send_email(subject, html)
    print("=== Done ===")


if __name__ == "__main__":
    main()
