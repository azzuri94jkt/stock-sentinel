"""Cron-style scheduler — runs the pipeline once per weekday at 21:00 UTC (7am AEST)."""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import schedule
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scheduler")


def _job():
    log.info("Scheduler triggered — starting pipeline")
    try:
        from pipeline.run_pipeline import run
        result = run()
        log.info("Pipeline finished with status: %s", result.get("status"))
    except Exception as exc:
        log.exception("Scheduled run failed: %s", exc)


# 21:00 UTC = 07:00 AEST (UTC+10), adjust for your timezone
schedule.every().monday.at("21:00").do(_job)
schedule.every().tuesday.at("21:00").do(_job)
schedule.every().wednesday.at("21:00").do(_job)
schedule.every().thursday.at("21:00").do(_job)
schedule.every().friday.at("21:00").do(_job)

log.info("Scheduler running — pipeline fires weekdays at 21:00 UTC (07:00 AEST)")
log.info("Next run: %s", schedule.next_run())

while True:
    schedule.run_pending()
    time.sleep(30)
