"""Synapse database package."""

from .database import Database
from .schema import SCHEMA_SQL, SCHEMA_VERSION, FTS_SQL

__all__ = ["Database", "SCHEMA_SQL", "SCHEMA_VERSION", "FTS_SQL"]
