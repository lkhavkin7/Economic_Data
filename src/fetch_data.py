import requests
import os
from datetime import datetime
from db_connection import get_db_connection

def fetch_gdp_data():
    """Fetch latest GDP data from FRED API"""
    API_KEY = os.getenv('FRED_API_KEY')
    
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": "GDP",
        "api_key": API_KEY,
        "file_type": "json",
        "limit": 5,  # Get last 5 quarters
        "sort_order": "desc"
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    return data['observations']

def insert_data(indicator_id, observations):
    """Insert economic data into database"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    inserted_count = 0
    
    for obs in observations:
        date = obs['date']
        value = obs['value']
        
        # Skip if value is '.' (missing data)
        if value == '.':
            continue
            
        try:
            cur.execute("""
                INSERT INTO economic_indicators (indicator_id, date, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (indicator_id, date) DO NOTHING
            """, (indicator_id, date, float(value)))
            
            if cur.rowcount > 0:
                inserted_count += 1
                
        except Exception as e:
            print(f"Error inserting {date}: {e}")
            continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    return inserted_count

if __name__ == "__main__":
    print("Fetching GDP data from FRED...")
    gdp_data = fetch_gdp_data()
    
    print(f"Found {len(gdp_data)} observations")
    
    inserted = insert_data("GDP", gdp_data)
    print(f"Inserted {inserted} new records into database")
    
    # Verify
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT date, value FROM economic_indicators WHERE indicator_id = 'GDP' ORDER BY date DESC LIMIT 5")
    results = cur.fetchall()
    
    print("\nLatest GDP data in database:")
    for date, value in results:
        print(f"  {date}: ${value:.2f} billion")
    
    cur.close()
    conn.close()