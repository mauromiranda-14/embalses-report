import asyncio
import os
import smtplib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from playwright.async_api import async_playwright

# ── Configuration (loaded from environment variables / GitHub Secrets) ───────
EMAIL_SENDER   = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
SMTP_HOST      = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.environ.get("SMTP_PORT", "587"))

RESERVOIRS = [
    {
        "name": "Rialb Embalse",
        "url":  "https://saihebro.org/tiempo-real/grafica-senal-E076O82PORCE--volumen-embalse-rialb",
        "cid":  "chart_rialb",
    },
    {
        "name": "Oliana SAI",
        "url":  "https://saihebro.org/tiempo-real/grafica-senal-E062O82PORCE--volumen-embalse-oliana",
        "cid":  "chart_oliana",
    },
]


async def capture_reservoir(page, reservoir: dict) -> dict:
    """Navigate to a reservoir chart page, extract data and take a screenshot."""
    print(f"  -> Loading {reservoir['name']} ...")
    await page.goto(reservoir["url"], wait_until="networkidle", timeout=60_000)

    # Wait until Highcharts has rendered at least one data point
    await page.wait_for_function(
        """() => {
            const charts = window.Highcharts?.charts?.filter(c => c && c.series?.length > 0);
            return charts && charts.length > 0 && charts[0].series[0].data.length > 0;
        }""",
        timeout=30_000,
    )

    # Extract latest value and 24h-ago value from Highcharts
    data = await page.evaluate(
        """() => {
            const chart  = window.Highcharts.charts.find(c => c && c.series?.length > 0);
            const series = chart.series[0];
            const pts    = series.data;
            const last   = pts[pts.length - 1];
            const prev24 = pts[Math.max(0, pts.length - 96)];

            const daily = {};
            pts.forEach(p => {
                const day = new Date(p.x).toLocaleDateString('es-ES');
                daily[day] = p.y;
            });

            return {
                seriesName:  series.name,
                chartTitle:  chart.title.textStr,
                latestValue: last?.y   ?? null,
                latestTime:  last  ? new Date(last.x).toLocaleString('es-ES') : null,
                value24hAgo: prev24?.y ?? null,
                dailySummary: daily,
            };
        }"""
    )

    screenshot_bytes = await page.screenshot(full_page=False)
    print(f"     OK  {data['seriesName']}: {data['latestValue']}% at {data['latestTime']}")
    return {"meta": data, "screenshot": screenshot_bytes, "cid": reservoir["cid"]}


def trend_arrow(current, previous) -> str:
    if previous is None or current is None:
        return "-"
    diff = current - previous
    if diff > 0.5:
        return f"+{diff:.2f}%"
    elif diff < -0.5:
        return f"{diff:.2f}%"
    return f"{diff:+.2f}%"


def build_html_email(results: list) -> str:
    today = datetime.now().strftime("%A, %d %B %Y - %H:%M")

    rows = ""
    for r in results:
        m     = r["meta"]
        trend = trend_arrow(m["latestValue"], m["value24hAgo"])
        val   = m["latestValue"] or 0
        color = "#2e7d32" if val >= 70 else ("#f57c00" if val >= 40 else "#c62828")
        rows += f"""
        <tr>
          <td style="padding:12px 16px;font-weight:bold;font-size:15px">{m['chartTitle']}</td>
          <td style="padding:12px 16px;text-align:center;font-size:22px;font-weight:bold;color:{color}">
            {m['latestValue']:.2f}%
          </td>
          <td style="padding:12px 16px;text-align:center;color:#555">{trend} (24h)</td>
          <td style="padding:12px 16px;text-align:center;color:#777;font-size:12px">{m['latestTime']}</td>
        </tr>"""

    chart_imgs = ""
    for r in results:
        chart_imgs += f"""
        <div style="margin-bottom:28px">
          <h3 style="margin:0 0 8px;color:#1a237e">{r['meta']['chartTitle']}</h3>
          <img src="cid:{r['cid']}" style="max-width:100%;border:1px solid #ddd;border-radius:4px"/>
          <p style="font-size:11px;color:#999;margin:4px 0 0">
            Fuente: <a href="https://saihebro.org">saihebro.org</a> &middot; Datos quinceminutales (ultimos 7 dias)
          </p>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:960px;margin:auto;padding:20px;color:#222">

  <div style="background:#1a237e;color:#fff;padding:18px 24px;border-radius:6px 6px 0 0">
    <h2 style="margin:0">Informe Diario de Embalses - SAIH Ebro</h2>
    <p  style="margin:4px 0 0;opacity:.8;font-size:13px">{today}</p>
  </div>

  <table style="width:100%;border-collapse:collapse;border:1px solid #ddd;border-top:none">
    <thead>
      <tr style="background:#e8eaf6;font-size:13px">
        <th style="padding:10px 16px;text-align:left">Embalse</th>
        <th style="padding:10px 16px">% Volumen actual</th>
        <th style="padding:10px 16px">Variacion (24h)</th>
        <th style="padding:10px 16px">Ultima lectura</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>

  <div style="margin-top:36px">{chart_imgs}</div>

  <p style="font-size:11px;color:#aaa;margin-top:24px;border-top:1px solid #eee;padding-top:12px">
    Informe generado automaticamente &middot;
    Sistema Automatico de Informacion Hidrologica del Ebro &middot;
    <a href="https://saihebro.org">saihebro.org</a>
  </p>
</body>
</html>"""


def send_email(subject: str, html_body: str, images: list):
    msg            = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER

    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(html_body, "html", "utf-8"))

    for img_bytes, cid in images:
        img = MIMEImage(img_bytes, "png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline")
        msg.attach(img)

    print(f"  -> Sending email to {EMAIL_RECEIVER} ...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print("  OK  Email sent successfully!")


async def main():
    print("=== SAIH Ebro Daily Reservoir Report ===")
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 860},
            locale="es-ES",
                        ignore_https_errors=True,
        )
        page = await context.new_page()

        for reservoir in RESERVOIRS:
            result = await capture_reservoir(page, reservoir)
            results.append(result)

        await browser.close()

    today_str = datetime.now().strftime("%d/%m/%Y")
    subject   = f"Embalses Rialb & Oliana - {today_str}"
    html      = build_html_email(results)
    images    = [(r["screenshot"], r["cid"]) for r in results]

    send_email(subject, html, images)
    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())