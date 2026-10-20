"""Memoise a service function per database file and its last-modified time.

The database is built once and read-only; a rebuild changes the file, which changes the key, so a stale answer cannot outlive
its data. Used by the services whose answers many screens and tools ask for again and again.
"""

from __future__ import annotations

import os
from functools import wraps

from sqlalchemy.orm import Session


def db_key(session: Session) -> tuple:
    path = session.get_bind().url.database or ":memory:"
    try:
        return (path, os.stat(path).st_mtime_ns)
    except OSError:
        return (path, 0)


def memo(fn):
    store: dict = {}

    @wraps(fn)
    def wrapper(session: Session, *args, **kwargs):
        key = (db_key(session), args, tuple(sorted(kwargs.items())))
        if key not in store:
            if len(store) > 512:
                store.clear()
            store[key] = fn(session, *args, **kwargs)
        return store[key]

    wrapper.cache_clear = store.clear
    return wrapper
