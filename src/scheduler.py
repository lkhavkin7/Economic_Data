import schedule
import time
from datetime import datetime
from fetch_data import fetch_and_store_indicator
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_pipeline.log'),
        logging.StreamHandler()
    ]
)

def run_daily_update():
    """Fetch latest data for all indicators"""
    logging.info("=" * 50)
    logging.info("Starting scheduled data update")
    logging.info("=" * 50)
    
    indicators = [
        ("GDP", "GDP", 5),
        ("FEDFUNDS", "FEDFUNDS", 10),
        ("UMCSENT", "UMCSENT", 5)
    ]
    
    total_inserted = 0
    
    for indicator_id, series_id, limit in indicators:
        try:
            inserted = fetch_and_store_indicator(indicator_id, series_id, limit)
            total_inserted += inserted
            logging.info(f"[OK] {indicator_id}: {inserted} new records")
        except Exception as e:
            logging.error(f"[FAIL] {indicator_id} failed: {e}")
    
    logging.info(f"Update complete. Total new records: {total_inserted}")
    logging.info("=" * 50)

def run_scheduler():
    """Run the scheduler"""
    logging.info("Economic Data Pipeline Scheduler Started")
    logging.info(f"Current time: {datetime.now()}")
    
    # Schedule daily updates at 9 AM
    schedule.every().day.at("09:00").do(run_daily_update)
    
    # For testing: also run every 5 minutes
    # schedule.every(5).minutes.do(run_daily_update)
    
    logging.info("Scheduled tasks:")
    logging.info("  - Daily update at 9:00 AM")
    
    # Run once immediately on startup
    logging.info("\nRunning initial update...")
    run_daily_update()
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    run_scheduler()