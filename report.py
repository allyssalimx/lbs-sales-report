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
TOKEN = os.environ["TELEGRAM_TOKEN"]
# TELEGRAM_CHAT may hold several chat IDs separated by commas (e.g. your private
# chat and a group), and every message/photo goes to all of them.
CHATS = [c.strip() for c in os.environ["TELEGRAM_CHAT"].split(",") if c.strip()]
TG = f"https://api.telegram.org/bot{TOKEN}"
STATE = "last_sent.txt"
MAX_BACKLOG = 7  # never try more than this many days back
# Only the day's LAST attempt sends a "still waiting" notice, so a day that
# isn't on the portal yet produces one message, not one per retry. The trigger
# passes FINAL=true on the final run of the day; manual runs default to true.
FINAL = os.environ.get("FINAL", "true").strip().lower()


def is_final_attempt():
    return FINAL != "false"


def tg_message(text):
    for chat in CHATS:
        requests.post(f"{TG}/sendMessage", json={"chat_id": chat, "text": text}, timeout=30).raise_for_status()


def tg_send_photo(path, caption):
    """Send the image to every destination. A read-timeout after upload almost
    always still means the photo was delivered (Telegram just answered slowly),
    so treat it as sent rather than crashing or re-sending a duplicate."""
    img = open(path, "rb").read()
    for chat in CHATS:
        try:
            r = requests.post(f"{TG}/sendPhoto",
                              data={"chat_id": chat, "caption": caption},
                              files={"photo": (path, img, "image/png")},
                              timeout=(15, 120))
            r.raise_for_status()
        except requests.exceptions.ReadTimeout:
            print(f"WARNING: sendPhoto read-timeout to {chat}; assuming delivered")
    return True


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
    tg_send_photo(out, caption)
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
            tg_message(f"Sales report for {pretty(day)} isn't in on the portal yet.")
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
            if is_final_attempt():
                tg_message(f"Sales report for {pretty(day)}: couldn't reach the portal ({e}).")
            else:
                print(f"portal error on non-final attempt, staying quiet: {e}")
            sys.exit(1)

        ready = bool(cs) and bool(gh)
        if not ready and (cs or gh) and day < yesterday:
            # Only one banner has data, but a later day exists: treat as final
            ready = True
        if not ready:
            if is_final_attempt():
                tg_message(f"Sales report for {pretty(day)} isn't in on the portal yet. "
                           f"It'll be sent automatically as soon as it appears.")
            else:
                print(f"{pretty(day)} not in yet; quiet until the day's final attempt")
            return

        send_report(day, cs, gh)
        open(STATE, "w").write(day.isoformat())
        day += timedelta(days=1)


if __name__ == "__main__":
    main()
