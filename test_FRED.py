import requests
import os

API_KEY = os.getenv("FRED_API_KEY")

url = f"https://api.stlouisfed.org/fred/series/observations"
params = {
    "series_id": "GDP",
    "api_key": API_KEY,
    "file_type": "json",
    "limit": 1,
    "sort_order": "desc"
}

response = requests.get(url, params=params)
data = response.json()

print('Latest GDP Data:')
print(data)