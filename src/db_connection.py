import psycopg2
import os

def get_db_connection():
    # Create a connection to the PostgreSQL database
    conn = psycopg2.connect(
        host="localhost",
        database="economic_data",
        user="postgres",
        password=os.getenv('POSTGRES_PASSWORD')
    )
    return conn

