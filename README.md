# LBS daily store sales report

Every day at about 6pm Singapore time, GitHub Actions gets the Cold Storage and Giant store sales for vendor 6483 for two days earlier, from the Cold Storage B2B portal (Store to Product). It draws them as one picture and sends it to Telegram.

- `report.py` gets the data and sends it to Telegram
- `render.py` draws the picture
- `.github/workflows/sales-report.yml` sets the schedule (`cron: "0 10 * * *"` = 6pm SGT)

Repository secrets needed: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT`.

To send a report now or for a particular date, go to **Actions → Daily store sales report → Run workflow** and optionally enter a date as YYYY-MM-DD.
