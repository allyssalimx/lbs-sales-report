"""Weekly / monthly Cold Storage + Giant store sales -> Telegram picture.

Same picture as the daily report, but each store's total is summed over a whole
week or month (the portal's date-range query does the summing).

The workflow sets MODE:
  MODE=week   -> previous Monday-Sunday week. Meant to go out the following
                 Monday; runs 3pm/6pm/9pm daily and keeps retrying until the
                 week's last day (Sunday) is on the portal.
  MODE=month  -> previous calendar month. Meant to go out on the 1st; same
                 retry cadence until the month's last day is on the portal.

Secrets: TELEGRAM_TOKEN, TELEGRAM_CHAT
State files (committed back by the workflow):
  week  -> last_sent_week.txt   holds the Sunday (YYYY-MM-DD) of the last week sent
  month -> last_sent_month.txt  holds the YYYY-MM of the last month sent
Manual run: set PERIOD to YYYY-MM-DD (any day in the wanted week) or YYYY-MM
(a month) to send just that one period without touching the state file.
"""
import calendar, json, os, subprocess, sys, time
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
MODE = os.environ.get("MODE", "week")
STATE = {"week": "last_sent_week.txt", "month": "last_sent_month.txt"}[MODE]
MAX_BACKLOG = 8  # periods
# Only the day's LAST attempt sends a "still waiting" notice, so a period that
# isn't on the portal yet gives one message per day, not one per retry. The
# trigger passes FINAL=true on the final run of the day; manual runs default true.
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


def portal_iso(d):
    # The portal keys a day's sales to that date at 16:00Z, e.g. 3 Nov -> 2026-11-03T16:00:00.000Z.
    # This matches exactly what the portal's own screen shows for that date.
    return f"{d.isoformat()}T16:00:00.000Z"


def fetch_day(banner, d):
    """One day's rows for a banner. [] means loaded-but-nothing; raises only on hard failure.

    The portal's range query times out past ~2 weeks, so weeks and months are
    built by summing single days, which stay fast and reliable.
    """
    url = (f"{API}?vendormastercode={VENDOR}++++++++++++++++&bannercode={banner}"
           f"&dateFrom={portal_iso(d)}&dateTo={portal_iso(d)}&userid={USERID}")
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


def period_ready(d_last):
    """True once the period's final day is on the portal (loads chronologically)."""
    return bool(fetch_day("CS", d_last)) and bool(fetch_day("GH", d_last))


def fetch_period(d1, d2):
    """Sum each store's sales day by day over d1..d2. Returns (cs, gh, complete).

    complete is False if any day has no data for either banner (not loaded yet),
    so a partially loaded period is retried rather than under-reported.
    """
    result, complete = {}, True
    day = d1
    while day <= d2:
        both_empty = True
        for banner in ("CS", "GH"):
            rows = fetch_day(banner, day)
            if rows:
                both_empty = False
            agg = result.setdefault(banner, {})
            for code, desc, amt in rows:
                cur = agg.setdefault(code, [desc, 0.0])
                cur[1] += amt
        if both_empty:
            complete = False
            break
        day += timedelta(days=1)
    to_rows = lambda b: sorted(([c, v[0], round(v[1], 2)] for c, v in result.get(b, {}).items()))
    return to_rows("CS"), to_rows("GH"), complete


def send_report(title, label, d1, d2):
    cs, gh, complete = fetch_period(d1, d2)
    if not complete or (not cs and not gh):
        return False
    data = {"title": title, "date": label, "vendor": "6483 – LBS Food Pte Ltd", "CS": cs or [], "GH": gh or []}
    json.dump(data, open("data.json", "w"))
    out = f"{MODE}_sales_{d1.isoformat()}_{d2.isoformat()}.png"
    subprocess.run([sys.executable, "render.py", "data.json", out], check=True)
    tot = lambda rows: sum(r[2] for r in rows)
    caption = (f"{title} — {label}\n"
               f"Cold Storage: ${tot(cs or []):,.2f} ({len(cs or [])} stores)\n"
               f"Giant: ${tot(gh or []):,.2f} ({len(gh or [])} stores)\n"
               f"Total: ${tot(cs or []) + tot(gh or []):,.2f}")
    tg_send_photo(out, caption)
    print("sent", out)
    return True


def next_try(now):
    h, today = now.hour, now.date()
    tomorrow = today + timedelta(days=1)
    if h < 15:
        return f"3pm today ({fmt_day(today)})"
    if h < 18:
        return f"6pm today ({fmt_day(today)})"
    if h < 21:
        return f"9pm today ({fmt_day(today)})"
    return f"3pm tomorrow ({fmt_day(tomorrow)})"


def fmt_day(d):
    return f"{d.day} {d.strftime('%b %Y')}"


# ---- period maths -----------------------------------------------------------

def week_of(any_day):
    """Return (monday, sunday) of the Mon-Sun week containing any_day."""
    monday = any_day - timedelta(days=any_day.weekday())  # Mon=0
    return monday, monday + timedelta(days=6)


def prev_week(today):
    """Most recent complete Mon-Sun week whose Sunday is before today."""
    last_sunday = today - timedelta(days=today.weekday() + 1)  # Mon->-1day ... Sun->-7days
    return last_sunday - timedelta(days=6), last_sunday


def month_of(any_day):
    first = any_day.replace(day=1)
    last = date(any_day.year, any_day.month, calendar.monthrange(any_day.year, any_day.month)[1])
    return first, last


def prev_month(today):
    first_this = today.replace(day=1)
    return month_of(first_this - timedelta(days=1))


def week_label(d1, d2):
    if d1.month == d2.month:
        return f"{d1.day}–{d2.day} {d2.strftime('%b %Y')}"
    if d1.year == d2.year:
        return f"{d1.day} {d1.strftime('%b')} – {d2.day} {d2.strftime('%b %Y')}"
    return f"{d1.day} {d1.strftime('%b %Y')} – {d2.day} {d2.strftime('%b %Y')}"


# ---- main -------------------------------------------------------------------

def period_key(d1, d2):
    """Stable id stored in the state file: Sunday date for a week, YYYY-MM for a month."""
    return d2.isoformat() if MODE == "week" else d1.strftime("%Y-%m")


def period_label(d1, d2):
    return week_label(d1, d2) if MODE == "week" else d1.strftime("%B %Y")


def target_period(today):
    return prev_week(today) if MODE == "week" else prev_month(today)


def step_back(d1):
    """Period immediately before the one starting at d1."""
    if MODE == "week":
        return week_of(d1 - timedelta(days=1))
    return month_of(d1 - timedelta(days=1))


def pending_periods(today):
    """Periods not yet sent, oldest first (normally just the one most recent period)."""
    stored = open(STATE).read().strip() if os.path.exists(STATE) else None
    d1, d2 = target_period(today)
    if stored is not None and period_key(d1, d2) == stored:
        return []  # most recent period already sent
    if stored is None:
        return [(d1, d2)]  # first run: only the most recent period, no history
    chain = [(d1, d2)]
    while len(chain) < MAX_BACKLOG:
        p1, p2 = step_back(chain[-1][0])
        if period_key(p1, p2) == stored:
            break          # reached the last one we already sent
        chain.append((p1, p2))
    return list(reversed(chain))


def main():
    now = datetime.now(SGT)
    today = now.date()
    title = "Weekly Store Sales" if MODE == "week" else "Monthly Store Sales"

    # Manual one-off: PERIOD = YYYY-MM-DD (any day in the week) or YYYY-MM (a month)
    if os.environ.get("PERIOD"):
        p = os.environ["PERIOD"]
        if MODE == "week":
            d1, d2 = week_of(date.fromisoformat(p))
        else:
            y, m = map(int, p.split("-")[:2])
            d1, d2 = month_of(date(y, m, 1))
        label = period_label(d1, d2)
        if not send_report(title, label, d1, d2):
            tg_message(f"{title} for {label}: no data on the portal.")
        return

    periods = pending_periods(today)
    if not periods:
        print("nothing pending")
        return

    for d1, d2 in periods:
        label = period_label(d1, d2)
        try:
            ready = period_ready(d2)
        except Exception as e:
            if is_final_attempt():
                tg_message(f"{title} for {label}: couldn't reach the portal ({e}).")
            else:
                print(f"portal error on non-final attempt, staying quiet: {e}")
            sys.exit(1)
        sent = send_report(title, label, d1, d2) if ready else False
        if not sent:
            if is_final_attempt():
                tg_message(f"{title} for {label} isn't fully in on the portal yet. "
                           f"It'll be sent automatically as soon as it appears.")
            else:
                print(f"{label} not fully in yet; quiet until the day's final attempt")
            return
        open(STATE, "w").write(period_key(d1, d2))


if __name__ == "__main__":
    main()
