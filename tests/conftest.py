"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Iterator

import pytest

from routeforge.accounts import AccountRepo
from routeforge.db import connect
from routeforge.secrets import Secrets

TEST_KEY = Secrets.generate_key()


@pytest.fixture
def secrets() -> Secrets:
    return Secrets(TEST_KEY)


@pytest.fixture
def conn(secrets: Secrets) -> Iterator[sqlite3.Connection]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        c = connect(path)
        yield c
        c.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


@pytest.fixture
def repo(conn: sqlite3.Connection, secrets: Secrets) -> AccountRepo:
    return AccountRepo(conn, secrets)
