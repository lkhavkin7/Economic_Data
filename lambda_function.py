import json
import os
from pathlib import Path

from src.fetch_data import fetch_and_store_indicator
from src.db_connection import get_db_connection


def _read_schema_sql():
    schema_path = Path(__file__).resolve().parent / 'db' / 'schema.sql'
    return schema_path.read_text(encoding='utf-8')


def _verify_database_contents():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT indicator_id, COUNT(*), MAX(date)
        FROM economic_indicators
        GROUP BY indicator_id
        ORDER BY indicator_id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            'indicator_id': row[0],
            'count': row[1],
            'max_date': str(row[2]) if row[2] else None,
        }
        for row in rows
    ]


def _ensure_database_and_schema():
    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME', 'econ_mcp')
    secret_arn = os.getenv('DB_SECRET_ARN')

    if not db_host or not secret_arn:
        raise ValueError('DB_HOST and DB_SECRET_ARN must be set for setup mode')

    import boto3
    import psycopg2

    secret_client = boto3.client('secretsmanager')
    secret_response = secret_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(secret_response['SecretString'])

    default_conn = psycopg2.connect(
        host=db_host,
        dbname='postgres',
        user=secret['username'],
        password=secret['password'],
        connect_timeout=10,
    )
    default_conn.autocommit = True
    default_cur = default_conn.cursor()

    default_cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    exists = default_cur.fetchone()
    if not exists:
        default_cur.execute(f'CREATE DATABASE "{db_name}"')
        created = True
    else:
        created = False

    default_cur.close()
    default_conn.close()

    target_conn = psycopg2.connect(
        host=db_host,
        dbname=db_name,
        user=secret['username'],
        password=secret['password'],
        connect_timeout=10,
    )
    target_cur = target_conn.cursor()
    schema_sql = _read_schema_sql()
    target_cur.execute(schema_sql)
    target_conn.commit()
    target_cur.close()
    target_conn.close()

    return {
        'database': db_name,
        'created': created,
        'schema_applied': True,
    }


def lambda_handler(event, context):
    payload = event or {}
    mode = payload.get('mode', 'fetch')

    if mode == 'verify':
        return {
            'mode': 'verify',
            'rows': _verify_database_contents(),
        }

    if mode == 'setup':
        result = _ensure_database_and_schema()
        return {
            'mode': 'setup',
            'database': result['database'],
            'created': result['created'],
            'schema_applied': result['schema_applied'],
        }

    indicators = [
        ("GDP", "GDP", 5),
        ("FEDFUNDS", "FEDFUNDS", 10),
        ("UMCSENT", "UMCSENT", 5),
    ]

    results = {}
    for indicator_id, series_id, limit in indicators:
        inserted = fetch_and_store_indicator(indicator_id, series_id, limit)
        results[indicator_id] = f"{inserted} new records"

    return results
