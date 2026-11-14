"""Database connections.

Credentials come from config. A password in config is used directly; otherwise
the secret named by the secret ARN in config is read from AWS Secrets Manager.
connection() opens a connection and always closes it.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

import psycopg2

from .config import Settings, load_settings

CONNECT_TIMEOUT_SECONDS = 10


def _fetch_secret(secret_arn: str) -> dict:
    """Read a JSON secret from AWS Secrets Manager and return it as a dict."""
    # Imported here so runs that use a password from config do not need boto3.
    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise ValueError("Secret has no SecretString")
    return json.loads(secret_string)


def get_credentials(settings: Settings) -> tuple[str, str]:
    """Return (user, password) for the database.

    A non-empty password in config wins. Otherwise the user and password are
    read from the secret. Raises ValueError if neither source is set.
    """
    if settings.db_password:
        return settings.db_user, settings.db_password

    if settings.db_secret_arn:
        secret = _fetch_secret(settings.db_secret_arn)
        user, password = secret.get("username"), secret.get("password")
        if not user or not password:
            raise ValueError("Secret is missing username or password")
        return user, password

    raise ValueError("No database credentials: set DB_PASSWORD or DB_SECRET_ARN")


def connect(settings: Settings | None = None):
    """Open a new connection. The caller is responsible for closing it."""
    settings = load_settings() if settings is None else settings
    user, password = get_credentials(settings)
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=user,
        password=password,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


@contextmanager
def connection(settings: Settings | None = None) -> Iterator:
    """Open a connection for a `with` block.

    Leaving the block normally commits. Leaving it with an exception rolls back
    and re-raises. The connection is closed in both cases.
    """
    conn = connect(settings)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()