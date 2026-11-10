name: Store sales reports

# Triggered by an external scheduler (cron-job.org) via the GitHub API, so runs
# start on time instead of waiting in GitHub's delayed schedule queue.
# The external scheduler calls this 3x/day (3pm, 6pm, 9pm Singapore):
#   3pm & 6pm  -> inputs.final = "false"  (retry quietly if data isn't in)
#   9pm        -> inputs.final = "true"   (send the one "still waiting" notice)
on:
  workflow_dispatch:
    inputs:
      final:
        description: 'true on the day''s last attempt (sends the "still waiting" notice)'
        required: false
        default: "true"
      report_date:
        description: "Daily one-off: send a specific day (YYYY-MM-DD)"
        required: false
      week_date:
        description: "Weekly one-off: any date in the week (YYYY-MM-DD)"
        required: false
      month:
        description: "Monthly one-off: a month (YYYY-MM)"
        required: false

permissions:
  contents: write

concurrency:
  group: store-sales-reports
  cancel-in-progress: false

jobs:
  reports:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: |
          pip install requests playwright
          python -m playwright install --with-deps chromium

      - name: Daily report
        if: always()
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT: ${{ secrets.TELEGRAM_CHAT }}
          FINAL: ${{ github.event.inputs.final }}
          REPORT_DATE: ${{ github.event.inputs.report_date }}
        run: python report.py

      - name: Weekly report
        if: always()
        env:
          MODE: week
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT: ${{ secrets.TELEGRAM_CHAT }}
          FINAL: ${{ github.event.inputs.final }}
          PERIOD: ${{ github.event.inputs.week_date }}
        run: python period_report.py

      - name: Monthly report
        if: always()
        env:
          MODE: month
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT: ${{ secrets.TELEGRAM_CHAT }}
          FINAL: ${{ github.event.inputs.final }}
          PERIOD: ${{ github.event.inputs.month }}
        run: python period_report.py

      - name: Save state
        if: always()
        run: |
          if [ -n "$(git status --porcelain last_sent.txt last_sent_week.txt last_sent_month.txt)" ]; then
            git config user.name "sales-report-bot"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add last_sent.txt last_sent_week.txt last_sent_month.txt
            git commit -m "Update report state"
            git pull --rebase --autostash origin "${{ github.ref_name }}" || true
            git push
          fi
