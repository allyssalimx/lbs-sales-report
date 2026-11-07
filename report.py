"""Daily Cold Storage + Giant store sales -> Telegram picture.

Runs on GitHub Actions. Needs two repository secrets:
  TELEGRAM_TOKEN  - your bot token from BotFather
  TELEGRAM_CHAT   - the chat id to send to
Optional: REPORT_DATE=YYYY-MM-DD to send a specific day (default: today - 2 days, Singapore time).
"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta, timezone
import requests

SGT = timezone(timedelta(hours=8))
API = "https://sphub.igo.com.sg/B2BAPI/SI/GetS2P"
VENDOR, USERID = "6483", "10010273"
TOKEN, CHAT = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT"]
TG = f"https://api.telegram.org/bot{TOKEN}"


def tg_message(text):
    requests.post(f"{TG}/sendMessage", json={"chat_id": CHAT, "text": text}, timeout=30).raise_for_status()


def fetch(banner, day):
    # Portal expects the UTC instant of local (SGT) midnight, e.g. 4 Nov -> 2026-11-03T16:00:00.000Z
    iso = (datetime(day.year, day.month, day.day, tzinfo=SGT).astimezone(timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    url = (f"{API}?vendormastercode={VENDOR}++++++++++++++++&bannercode={banner}"
           f"&dateFrom={iso}&dateTo={iso}&userid={USERID}")
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (sales-report)"})
            r.raise_for_status()
            return [[s["storecode"].strip(), s["storedesc"], s["salesamount"]] for s in r.json()]
        except Exception as e:
            err = e
            time.sleep(10)
    raise RuntimeError(f"{banner}: {err}")


def main():
    if os.environ.get("REPORT_DATE"):
        day = datetime.strptime(os.environ["REPORT_DATE"], "%Y-%m-%d").date()
    else:
        day = (datetime.now(SGT) - timedelta(days=2)).date()
    pretty = f"{day.day} {day.strftime('%b %Y')}"

    try:
        cs, gh = fetch("CS", day), fetch("GH", day)
    except Exception as e:
        tg_message(f"Sales report for {pretty}: couldn't reach the portal ({e}).")
        sys.exit(1)

    if not cs and not gh:
        tg_message(f"Sales report for {pretty} isn't ready on the portal yet.")
        return

    data = {"date": pretty, "vendor": "6483 – LBS Food Pte Ltd", "CS": cs, "GH": gh}
    json.dump(data, open("data.json", "w"))
    out = f"store_sales_{day.isoformat()}.png"
    subprocess.run([sys.executable, "render.py", "data.json", out], check=True)

    tot = lambda rows: sum(r[2] for r in rows)
    caption = (f"Store sales {pretty}\n"
               f"Cold Storage: ${tot(cs):,.2f} ({len(cs)} stores)\n"
               f"Giant: ${tot(gh):,.2f} ({len(gh)} stores)\n"
               f"Total: ${tot(cs) + tot(gh):,.2f}")
    with open(out, "rb") as f:
        r = requests.post(f"{TG}/sendPhoto", data={"chat_id": CHAT, "caption": caption},
                          files={"photo": (out, f, "image/png")}, timeout=60)
    r.raise_for_status()
    print("sent", out)


if __name__ == "__main__":
    main()
