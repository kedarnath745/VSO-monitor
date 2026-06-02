"""
VSO Project Monitor
Fetches https://vso.manipal.edu/Projects.aspx, compares projects against
the last known state, and sends a Gmail alert when new ones appear.
Run by GitHub Actions every 15 minutes — works even when Chrome is closed.
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

URL            = "https://vso.manipal.edu/Projects.aspx"
STATE_FILE     = Path("last_known_projects.json")   # committed back to repo

# Loaded from GitHub Secrets (set once in your repo settings)
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")   # your Gmail address
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "") # Gmail App Password
EMAIL_TO       = os.environ.get("EMAIL_TO", "")     # where to send alerts

# ── Fetch & parse ─────────────────────────────────────────────────────────────

def fetch_projects():
    headers = {"User-Agent": "Mozilla/5.0 (VSO-Monitor/1.0)"}
    res = requests.get(URL, headers=headers, timeout=15)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")
    projects = []

    # Find the "PROJECTS THIS WEEK" section and its table
    for heading in soup.find_all(["h5", "h4", "h3"]):
        if "PROJECTS THIS WEEK" in heading.get_text(strip=True).upper():
            table = heading.find_next("table")
            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 3:
                        name   = cells[0].get_text(strip=True)
                        date   = cells[1].get_text(strip=True)
                        timing = cells[2].get_text(strip=True)
                        if name and date:
                            projects.append({
                                "name":   name,
                                "date":   date,
                                "timing": timing
                            })
            break

    # Also check WEEKLY PROJECTS and SPECIAL PROJECTS sections
    for heading in soup.find_all(["h5", "h4", "h3", "a"]):
        text = heading.get_text(strip=True).upper()
        if "WEEKLY PROJECTS" in text or "SPECIAL PROJECTS" in text:
            table = heading.find_next("table")
            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 3:
                        name   = cells[0].get_text(strip=True)
                        date   = cells[1].get_text(strip=True)
                        timing = cells[2].get_text(strip=True)
                        if name and date:
                            proj = {"name": name, "date": date, "timing": timing}
                            if proj not in projects:
                                projects.append(proj)

    return projects

# ── State management ──────────────────────────────────────────────────────────

def load_known():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return []

def save_known(projects):
    STATE_FILE.write_text(json.dumps(projects, indent=2))

def find_new(current, known):
    known_keys = {(p["name"], p["date"]) for p in known}
    return [p for p in current if (p["name"], p["date"]) not in known_keys]

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(new_projects):
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        print("⚠️  Email secrets not configured. Skipping email.")
        return

    subject = (
        f"🔔 {'New VSO Project' if len(new_projects) == 1 else f'{len(new_projects)} New VSO Projects'} — Register Now!"
    )

    # Plain text version
    lines = [f"New project(s) appeared on the VSO portal:\n"]
    for p in new_projects:
        lines.append(f"  • {p['name']}")
        lines.append(f"    Date: {p['date']}  |  Timings: {p['timing']}")
        lines.append("")
    lines.append(f"Register here: {URL}")
    plain = "\n".join(lines)

    # HTML version
    cards = ""
    for p in new_projects:
        cards += f"""
        <div style="border:1px solid #ddd;border-radius:8px;padding:14px 16px;
                    margin-bottom:12px;background:#fff;">
          <div style="font-size:15px;font-weight:700;color:#1a1a1a;">{p['name']}</div>
          <div style="font-size:13px;color:#555;margin-top:4px;">
            📅 {p['date']} &nbsp;|&nbsp; ⏰ {p['timing']}
          </div>
        </div>"""

    html = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;">
      <div style="background:#006064;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;font-size:18px;">🔔 VSO Project Alert</h2>
        <p style="color:rgba(255,255,255,.8);margin:4px 0 0;font-size:13px;">
          New project(s) just appeared — spots are limited, register quickly!
        </p>
      </div>
      <div style="padding:20px;background:#f7f7f7;border-radius:0 0 8px 8px;">
        {cards}
        <a href="{URL}"
           style="display:block;text-align:center;background:#006064;color:#fff;
                  padding:12px;border-radius:6px;text-decoration:none;
                  font-weight:700;font-size:14px;margin-top:8px;">
          Register Now →
        </a>
        <p style="font-size:11px;color:#999;text-align:center;margin-top:12px;">
          Checked at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
        </p>
      </div>
    </div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

    print(f"✅ Email sent to {EMAIL_TO}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.utcnow().isoformat()}] Checking {URL} …")

    current = fetch_projects()
    print(f"  Found {len(current)} project(s) on page.")

    known = load_known()
    new   = find_new(current, known)

    if new:
        print(f"  🆕 {len(new)} new project(s): {[p['name'] for p in new]}")
        send_email(new)
    else:
        print("  No new projects.")

    # Merge and save updated state
    all_keys = {(p["name"], p["date"]) for p in known}
    merged = known + [p for p in current if (p["name"], p["date"]) not in all_keys]
    save_known(merged)
    print("  State saved.")

if __name__ == "__main__":
    main()
