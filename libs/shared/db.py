import sys
import os
# Ensure the project root is in sys.path regardless of how the worker is started
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if root_dir not in sys.path:
	sys.path.insert(0, root_dir)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()

# --- Context manager for safe DB session handling ---
from contextlib import contextmanager
from sqlalchemy.orm import Session

@contextmanager
def get_db_session():
	session = None
	try:
		from libs.shared.config import settings
		from sqlalchemy import create_engine
		from sqlalchemy.orm import sessionmaker
		engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=300)
		SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
		session = SessionLocal()
		yield session
	except Exception:
		if session is not None:
			session.rollback()
		raise
	finally:
		if session is not None:
			session.close()