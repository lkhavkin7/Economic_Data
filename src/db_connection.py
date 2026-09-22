import json
import os

try:
    import boto3
except ModuleNotFoundError:  # pragma: no cover - exercised when the runtime is not installed locally
    boto3 = None

try:
    import psycopg2
except ModuleNotFoundError:  # pragma: no cover - exercised when the runtime is not installed locally
    psycopg2 = None


def get_db_connection():
    if boto3 is None:
        raise ModuleNotFoundError('boto3 is required. Install project dependencies with pip install -r requirements.txt.')
    if psycopg2 is None:
        raise ModuleNotFoundError('psycopg2 is required. Install project dependencies with pip install -r requirements.txt.')

    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME', 'econ_mcp')
    secret_arn = os.getenv('DB_SECRET_ARN')

    if not db_host:
        raise ValueError('DB_HOST environment variable is required')
    if not secret_arn:
        raise ValueError('DB_SECRET_ARN environment variable is required')

    secret_client = boto3.client('secretsmanager')
    response = secret_client.get_secret_value(SecretId=secret_arn)
    secret_string = response.get('SecretString')

    if not secret_string:
        raise ValueError('RDS secret did not contain a SecretString')

    secret = json.loads(secret_string)
    username = secret.get('username')
    password = secret.get('password')

    if not username or not password:
        raise ValueError('RDS secret is missing username/password fields')

    conn = psycopg2.connect(
        host=db_host,
        database=db_name,
        user=username,
        password=password,
        connect_timeout=10,
    )
    return conn

