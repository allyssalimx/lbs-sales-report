"""Daily Cold Storage + Giant store sales -> Telegram picture.

Runs on GitHub Actions at 3pm, 6pm and 9pm Singapore time.
Each run sends every day that hasn't been sent yet (normally just yesterday),
oldest first. If a day's data isn't on the portal yet, it stops and the next
scheduled run (6pm, 9pm, then 3pm the next day, ...) tries again.
The last day sent is remembered in last_sent.txt, which the workflow commits back.

Repository secrets: TELEGRAM_TOKEN, TELEGRAM_CHAT
Manual run: REPORT_DATE=YYYY-MM-DD sends that one day (doesn't change last_sent.txt).
"""
import json, os, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone
import requests

SGT = timezone(timedelta(hours=8))
API = "https://sphub.igo.com.sg/B2BAPI/SI/GetS2P"
VENDOR, USERID = "6483", "10010273"
TOKEN, CHAT = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT"]
TG = f"https://api.telegram.org/bot{TOKEN}"
STATE = "last_sent.txt"
MAX_BACKLOG = 7  # never try more than this many days back


def tg_message(text):
    requests.post(f"{TG}/sendMessage", json={"chat_id": CHAT, "text": text}, timeout=30).raise_for_status()


def pretty(d):
    return f"{d.day} {d.strftime('%b %Y')}"


def portal_iso(d):
    # The portal keys a day's sales to that date at 16:00Z, e.g. 3 Nov -> 2026-11-03T16:00:00.000Z.
    # This matches exactly what the portal's own screen shows for that date.
    return f"{d.isoformat()}T16:00:00.000Z"


def fetch(banner, day):
    iso = portal_iso(day)
    url = (f"{API}?vendormastercode={VENDOR}++++++++++++++++&bannercode={banner}"
           f"&dateFrom={iso}&dateTo={iso}&userid={USERID}")
    err = None
    for _ in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (sales-report)"})
            r.raise_for_status()
            return [[s["storecode"].strip(), s["storedesc"], s["salesamount"]] for s in r.json()]
        except Exception as e:
            err = e
            time.sleep(10)
    raise RuntimeError(f"{banner}: {err}")


def send_report(day, cs, gh):
    data = {"date": pretty(day), "vendor": "6483 – LBS Food Pte Ltd", "CS": cs, "GH": gh}
    json.dump(data, open("data.json", "w"))
    out = f"store_sales_{day.isoformat()}.png"
    subprocess.run([sys.executable, "render.py", "data.json", out], check=True)
    tot = lambda rows: sum(r[2] for r in rows)
    caption = (f"Store sales {pretty(day)}\n"
               f"Cold Storage: ${tot(cs):,.2f} ({len(cs)} stores)\n"
               f"Giant: ${tot(gh):,.2f} ({len(gh)} stores)\n"
               f"Total: ${tot(cs) + tot(gh):,.2f}")
    with open(out, "rb") as f:
        r = requests.post(f"{TG}/sendPhoto", data={"chat_id": CHAT, "caption": caption},
                          files={"photo": (out, f, "image/png")}, timeout=60)
    r.raise_for_status()
    print("sent", out)


def next_try(now):
    h, today = now.hour, now.date()
    tomorrow = today + timedelta(days=1)
    if h < 15:
        return f"3pm today ({pretty(today)})"
    if h < 18:
        return f"6pm today ({pretty(today)})"
    if h < 21:
        return f"9pm today ({pretty(today)})"
    return f"3pm tomorrow ({pretty(tomorrow)})"


def main():
    now = datetime.now(SGT)
    yesterday = (now - timedelta(days=1)).date()

    if os.environ.get("REPORT_DATE"):  # manual one-off
        day = datetime.strptime(os.environ["REPORT_DATE"], "%Y-%m-%d").date()
        cs, gh = fetch("CS", day), fetch("GH", day)
        if not cs and not gh:
            tg_message(f"Sales report for {pretty(day)} isn't in on the portal yet. "
                       f"Next automatic try: {next_try(now)}.")
        else:
            send_report(day, cs, gh)
        return

    if os.path.exists(STATE):
        last = date.fromisoformat(open(STATE).read().strip())
        start = max(last + timedelta(days=1), yesterday - timedelta(days=MAX_BACKLOG - 1))
    else:
        start = yesterday  # first ever run: start from yesterday
    if start > yesterday:
        print("nothing to send; last sent", last)
        return

    day = start
    while day <= yesterday:
        try:
            cs, gh = fetch("CS", day), fetch("GH", day)
        except Exception as e:
            tg_message(f"Sales report for {pretty(day)}: couldn't reach the portal ({e}). "
                       f"Will try again at {next_try(now)}.")
            sys.exit(1)

        ready = bool(cs) and bool(gh)
        if not ready and (cs or gh) and day < yesterday:
            # Only one banner has data, but a later day exists: treat as final
            ready = True
        if not ready:
            tg_message(f"Sales report for {pretty(day)} isn't in on the portal yet. "
                       f"Will try again at {next_try(now)}.")
            return

        send_report(day, cs, gh)
        open(STATE, "w").write(day.isoformat())
        day += timedelta(days=1)


if __name__ == "__main__":
    main()
