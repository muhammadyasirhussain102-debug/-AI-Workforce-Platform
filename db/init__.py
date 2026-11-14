"""
Database package for employee management system.
Provides models base, database session handlers, and public SQL view contracts.
"""

from db.base import Base
from db.session import get_db, engine, SessionLocal

__all__ = ["Base", "get_db", "engine", "SessionLocal"]