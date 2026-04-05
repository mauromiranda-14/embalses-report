import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import urllib3
import re

# -- Configuration
EMAIL_SENDER  = os.environ["EMAIL_SENDER"]
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
        "nivel_tag": "E076O17NEMBA",
        "station": "E076",
        "label": "% Volumen Embalse Rialb",
        "url": "https://saihebro.org/tiempo-real/grafica-senal-E076O82PORCE--volumen-embalse-rialb",
    },
    {
        "name": "Oliana SAI",
        "tag": "E062O82PORCE",
        "nivel_tag": "E062O17NEMBA",
        "station": "E062",
        "label": "% Volumen Embalse Oliana",
        "url": "https://saihebro.org/tiempo-real/grafica-senal-E062O82PORCE--volumen-embalse-oliana",
    },
        {
                    "name": "Bachimana Superior",
                    "tag": "E034Z82PORCE",
                    "nivel_tag": None,
                    "station": "E034",
                    "label": "% Volumen Embalse Bachimana Superior",
                    "url": "https://saihebro.org/tiempo-real/grafica-senal-E034Z82PORCE-volumen-embalse-bachimana-superior",
        },
]

# -- SAIH Cantabrico Configuration
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


def fetch_volumenes_embalsados():
    """Fetch current % volume for all SAIH Ebro reservoirs via GET endpoint.

    Returns a dict keyed by station code (e.g. "E076") with the current
    percentage volume and absolute volume in hm3.
    This endpoint is a simple GET and works from cloud IPs.
    """
    url = f"{BASE_URL}/api/principal/getVolumenesEmbalsados"
    print("--> Fetching volumenes embalsados (GET fallback)")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, verify=False)
        resp.raise_for_status()
        data = resp.json()
        result = {}
        for key, val in data.get("volumenes", {}).items():
            if key.startswith("E") and key[1:].isdigit():
                # data[1] is "Volumen actual" (current): {y: %, volumen: "hm3"}
                current = val.get("data", [None, None])[1]
                if current:
                    result[key] = {
                        "pct": current.get("y") if isinstance(current, dict) else current,
                        "vol_hm3": float(current["volumen"]) if isinstance(current, dict) else None,
                        "zona": val.get("zona", ""),
                    }
        print(f"  Got data for {len(result)} reservoirs")
        return result
    except Exception as e:
        print(f"  Failed to fetch volumenes embalsados: {e}")
        return {}


def fetch_ficha_valor_actual(station, tag):
        """Fetch current value from the ficha endpoint (GET, works from cloud IPs).

            Uses /api/ficha/procesarTablaValoresActuales which returns HTML with
                the latest sensor values. We parse the aria-label to extract the
                    percentage value for the given tag.
                        """
        url = f"{BASE_URL}/api/ficha/procesarTablaValoresActuales?estacion={station}"
        print(f"  Trying ficha fallback for {station} (tag={tag})")
        try:
                    resp = requests.get(url, headers=HEADERS, timeout=30, verify=False)
                    resp.raise_for_status()
                    data = resp.json()
                    html = data.get("VALORES_ACTUALES", "")
                    # Find the tag in the HTML and extract the percentage value
        if tag in html:
                        tag_pos = html.index(tag)
                        section = html[tag_pos:tag_pos + 500]
                        match = re.search(r"aria-label='Valor\s+([\d,.]+)\s+%'", section)
                        if match:
                                            val_str = match.group(1).replace(",", ".")
                                            val = float(val_str)
                                            print(f"  Got ficha value: {val}%")
                                            return val
                                    print(f"  Tag {tag} not found in ficha response")
        return None
except Exception as e:
        print(f"  Ficha fallback failed: {e}")
        return None

def fetch_reservoir_info(reservoir, fallback_data=None):
    tag = reservoir["tag"]
    nivel_tag = reservoir.get("nivel_tag")
    station = reservoir.get("station", "")
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

    # Find the nivel signal metadata
    nivel_key = f"{nivel_tag}|VALOR" if nivel_tag else None
    nivel_meta = meta_json["metaData"].get(nivel_key) if nivel_key else None
    if nivel_meta is None and nivel_tag:
        for k, v in meta_json["metaData"].items():
            if v.get("LS_UNID_ING") == "msnm":
                nivel_key = k
                nivel_meta = v
                break

    # Try to get actual data via POST (may fail from cloud IPs)
    latest_val = None
    latest_nivel = None
    try:
        if pct_meta is not None:
            # Build metaData and senalesSeleccionadas including nivel if available
            req_meta = {pct_key: pct_meta}
            req_senales = [pct_meta["TAG"]]
            if nivel_meta is not None:
                req_meta[nivel_key] = nivel_meta
                req_senales.append(nivel_meta["TAG"])

            payload = {
                "fechaIni": fecha_ini,
                "fechaFin": fecha_fin,
                "metaData": req_meta,
                "senalesSeleccionadas": req_senales,
                "tipoConsolidado": meta_json["tipoConsolidado"],
            }
            data_url = f"{BASE_URL}/api/datos-graficas/obtenerGraficaHistorica"
            resp = session.post(data_url, json=payload, timeout=60)

            print("STATUS:", resp.status_code)

            if resp.status_code == 200:
                data_json = resp.json()

                # Extract percentage value
                if pct_key in data_json:
                    datos = data_json[pct_key].get("DATOS", [])
                    if datos:
                        latest_val = datos[-1][1]
                        print(f"  Got % value from API: {latest_val}%")

                # Extract nivel value
                if nivel_key and nivel_key in data_json:
                    datos_nivel = data_json[nivel_key].get("DATOS", [])
                    if datos_nivel:
                        latest_nivel = datos_nivel[-1][1]
                        print(f"  Got nivel value from API: {latest_nivel} msnm")
            else:
                print(f"  POST returned {resp.status_code} (expected from cloud IPs)")
    except Exception as e:
        print(f"  POST failed: {e}")

    # Fallback: use getVolumenesEmbalsados data if POST failed
    if latest_val is None and fallback_data and station in fallback_data:
        fb = fallback_data[station]
        latest_val = fb.get("pct")
        print(f"  Using fallback % value: {latest_val}%")

    # Secondary fallback: use ficha endpoint (GET, works from cloud IPs)
    if latest_val is None and station:
                latest_val = fetch_ficha_valor_actual(station, tag)

    return {
        "name": reservoir["name"],
        "tag": tag,
        "label": pct_meta["DESCRIPCION"] if pct_meta else reservoir["label"],
        "nivel_label": nivel_meta["DESCRIPCION"] if nivel_meta else None,
        "url": reservoir["url"],
        "fecha_ini": fecha_ini,
        "fecha_fin": fecha_fin,
        "latest": latest_val,
        "latest_nivel": latest_nivel,
    }


def fetch_la_cohilla_info():
    """Fetch La Cohilla reservoir data from SAIH Cantabrico."""
    print("--> Fetching info for La Cohilla (codigo=1253)")

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
                    print(f"  Got value from API: {latest_val}%")
                    break
            else:
                print("  Station 1253 not found in response")
        else:
            print("  API returned success=false")
    except Exception as e:
        print(f"  Failed to fetch La Cohilla data: {e}")

    return {
        "name": LA_COHILLA["name"],
        "tag": LA_COHILLA["codigo"],
        "label": LA_COHILLA["label"],
        "nivel_label": None,
        "url": LA_COHILLA["url"],
        "fecha_ini": None,
        "fecha_fin": None,
        "latest": latest_val,
        "latest_nivel": None,
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
    <html><body style="font-family:Arial,sans-serif;max-width:650px;margin:0 auto;">
    <div style="background:#2a7ab5;color:white;padding:15px;text-align:center;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">Embalses Rialb, Oliana, Bachimana &amp; La Cohilla</h2>
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
            Fuente: <a href="https://saihebro.org" style="color:#2a7ab5;">SAIH Ebro</a> |
            <a href="https://visor.saichcantabrico.es" style="color:#2a7ab5;">SAIH Cantabrico</a><br>
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
    print(f"  Email sent to {EMAIL_RECEIVER}")


def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    print("=== SAIH Ebro & Cantabrico Daily Reservoir Report ===")

    # Pre-fetch fallback data (works from cloud IPs)
    fallback_data = fetch_volumenes_embalsados()

    results = []
    for reservoir in RESERVOIRS:
        info = fetch_reservoir_info(reservoir, fallback_data=fallback_data)
        results.append(info)

    # Fetch La Cohilla from SAIH Cantabrico
    cohilla_info = fetch_la_cohilla_info()
    results.append(cohilla_info)

    today_str = datetime.now().strftime("%d/%m/%Y")
    subject = f"Embalses Rialb, Oliana, Bachimana & La Cohilla - {today_str}"
    html = build_html(results)
    send_email(subject, html)
    print("=== Done ===")


if __name__ == "__main__":
    main()
