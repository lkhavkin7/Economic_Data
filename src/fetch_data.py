import requests
import os
from datetime import datetime
from db_connection import get_db_connection
from validate_data import validate_value, validate_date

def fetch_fred_data(series_id, limit=5):
    """
    Fetch data for any FRED series

    Args:
        series_id: FRED series identifier (e.g., 'GDP', 'FEDFUNDS')
        limit: Number of recent observations to fetch
    
    Returns:
        List of observations from FRED API
    """
    API_KEY = os.getenv('FRED_API_KEY')
    
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": API_KEY,
        "file_type": "json",
        "limit": limit,
        "sort_order": "desc"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises error for bad status codes
        data = response.json()
        return data['observations']
    except requests.exceptions.RequestException as e:
        print(f"API error: {e}")
        return []  # Return empty list on failure
    
    

def insert_data(indicator_id, observations):
    """Insert economic data into database with validation"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    inserted_count = 0
    skipped_count = 0
    validation_failures = []
    
    for obs in observations:
        date = obs['date']
        value = obs['value']
        
        # Skip if value is '.' (missing data)
        if value == '.':
            skipped_count += 1
            continue
        
        # Validate date
        date_valid, date_error = validate_date(date)
        if not date_valid:
            validation_failures.append(date_error)
            skipped_count += 1
            continue
        
        # Validate value
        try:
            numeric_value = float(value)
        except ValueError:
            validation_failures.append(f"Invalid numeric value: {value}")
            skipped_count += 1
            continue
        
        value_valid, value_error = validate_value(indicator_id, numeric_value)
        if not value_valid:
            validation_failures.append(value_error)
            skipped_count += 1
            continue
            
        # Insert if all validations pass
        try:
            cur.execute("""
                INSERT INTO economic_indicators (indicator_id, date, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (indicator_id, date) DO NOTHING
            """, (indicator_id, date, numeric_value))
            # Prevent duplicate data - if same indicator and date exists, skip insertion

            if cur.rowcount > 0:
                inserted_count += 1
                
        except Exception as e:
            validation_failures.append(f"Database error for {date}: {e}")
            skipped_count += 1
            continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    # Print validation failures if any
    if validation_failures:
        print(f"  Validation failures:")
        for failure in validation_failures[:5]:  # Show first 5
            print(f"    - {failure}")
        if len(validation_failures) > 5:
            print(f"    ... and {len(validation_failures) - 5} more")
    
    return inserted_count, skipped_count

def fetch_and_store_indicator(indicator_id, series_id, limit=5):
    """Fetch and store data for a specific indicator"""
    print(f"\nFetching {indicator_id} data from FRED...")
    
    observations = fetch_fred_data(series_id, limit)
    print(f"  Found {len(observations)} observations")
    
    inserted, skipped = insert_data(indicator_id, observations)
    print(f"  Inserted: {inserted}, Skipped: {skipped}")
    
    return inserted

if __name__ == "__main__":
    # Fetch all 3 indicators
    indicators = [
        ("GDP", "GDP", 5),
        ("FEDFUNDS", "FEDFUNDS", 10),  # More data points since it's daily
        ("UMCSENT", "UMCSENT", 5)
    ]
    
    total_inserted = 0
    
    for indicator_id, series_id, limit in indicators:
        inserted = fetch_and_store_indicator(indicator_id, series_id, limit)
        total_inserted += inserted
    
    print(f"\n{'='*50}")
    print(f"Total new records inserted: {total_inserted}")
    print(f"{'='*50}")
    
    # Show latest data for each indicator
    conn = get_db_connection()
    cur = conn.cursor()
    
    print("\nLatest data in database:")
    for indicator_id, _, _ in indicators:
        cur.execute("""
            SELECT date, value 
            FROM economic_indicators 
            WHERE indicator_id = %s 
            ORDER BY date DESC 
            LIMIT 3
        """, (indicator_id,))
        
        results = cur.fetchall()
        print(f"\n{indicator_id}:")
        for date, value in results:
            print(f"  {date}: {value}")
    
    cur.close()
    conn.close()