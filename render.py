"""Render the Store-to-Product store totals (Cold Storage + Giant) as one PNG.
Usage: python3 render_report.py data.json out.png
data.json: {"date": "4 Nov 2026", "vendor": "...", "CS": [[code, name, amt], ...], "GH": [...]}
"""
import json, sys, html
from playwright.sync_api import sync_playwright

data = json.load(open(sys.argv[1]))
out = sys.argv[2]

def panel(title, accent, rows):
    rows = sorted(rows, key=lambda r: -r[2])
    total = sum(r[2] for r in rows)
    top = rows[0][2] if rows else 1
    trs = "".join(
        f"<tr><td class=rk>{i+1}</td><td class=cd>{html.escape(c)}</td>"
        f"<td class=nm>{html.escape(n.upper())}</td>"
        f"<td class=bar><div style='width:{a/top*100:.1f}%;background:{accent}'></div></td>"
        f"<td class=amt>{a:,.2f}</td></tr>"
        for i, (c, n, a) in enumerate(rows))
    return f"""<section><header style='border-color:{accent}'>
<div><h2>{title}</h2><span>{len(rows)} stores</span></div>
<div class=tot><small>Total sales</small><b>${total:,.2f}</b></div></header>
<table>{trs}</table></section>"""

grand = sum(r[2] for r in data["CS"]) + sum(r[2] for r in data["GH"])
page = f"""<!doctype html><html><head><meta charset=utf-8><style>
*{{box-sizing:border-box;margin:0}}
body{{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f4f5f7;color:#1d2330;padding:28px;width:1500px}}
.top{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:20px}}
h1{{font-size:26px}} .sub{{color:#5b6475;font-size:15px;margin-top:4px}}
.grand{{text-align:right}} .grand small{{display:block;color:#5b6475;font-size:13px}} .grand b{{font-size:28px}}
.cols{{display:grid;grid-template-columns:1.25fr 1fr;gap:20px;align-items:start}}
section{{background:#fff;border-radius:12px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
header{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid;padding-bottom:10px;margin-bottom:6px}}
h2{{font-size:19px}} header span{{color:#5b6475;font-size:13px}}
.tot{{text-align:right}} .tot small{{display:block;color:#5b6475;font-size:12px}} .tot b{{font-size:22px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
td{{padding:5px 4px;border-bottom:1px solid #eef0f3;white-space:nowrap}}
.rk{{color:#8a93a3;width:26px;text-align:right;padding-right:8px}} .cd{{color:#5b6475;width:52px;font-variant-numeric:tabular-nums}}
.nm{{width:230px}} .bar{{width:auto}} .bar div{{height:12px;border-radius:3px;min-width:2px}}
.amt{{text-align:right;width:90px;font-variant-numeric:tabular-nums;font-weight:600}}
</style></head><body>
<div class=top><div><h1>{html.escape(data.get('title', 'Store Sales Report'))} · {html.escape(data['date'])}</h1>
<div class=sub>Vendor {html.escape(data['vendor'])} · Cold Storage B2B Portal, Store to Product · amounts in SGD</div></div>
<div class=grand><small>Cold Storage + Giant</small><b>${grand:,.2f}</b></div></div>
<div class=cols>{panel('Cold Storage', '#2f6fd1', data['CS'])}{panel('Giant', '#d9822b', data['GH'])}</div>
</body></html>"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1556, "height": 800}, device_scale_factor=2)
    pg.set_content(page)
    pg.locator("body").screenshot(path=out)
    b.close()
print("ok", out)
