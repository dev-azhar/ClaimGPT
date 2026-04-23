import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine

# 1. Setup paths
root = os.path.abspath(os.getcwd())
sys.path.append(root)
sys.path.append(os.path.join(root, "services", "parser", "app"))

load_dotenv()

# 2. Get your DB URL from .env
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fallback to standard local dev string if .env is missing it
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/claimgpt"

try:
    engine = create_engine(DATABASE_URL)

    # 3. Import the Bases



    # Parser Base from services
    # Explicitly import all coding models so SQLAlchemy registers them
    from services.coding.app import models as coding_models  # noqa: F401

    # Coding Base from services
    from services.coding.app.db import Base as CodingBase
    from services.parser.app.models import Base as ParserBase

    # Explicitly import all predictor models so SQLAlchemy registers them
    from services.predictor.app import models as predictor_models  # noqa: F401

    # Predictor Base from services
    from services.predictor.app.db import Base as PredictorBase

    print(f"Connecting to: {DATABASE_URL}")

    # 4. Create all tables

    print("Registering Parser tables...")
    ParserBase.metadata.create_all(bind=engine)


    print("Registering Coding tables...")
    CodingBase.metadata.create_all(bind=engine)

    print("Registering Predictor tables...")
    PredictorBase.metadata.create_all(bind=engine)

    print("✅ SUCCESS: All tables including 'medical_codes' and 'features' are created!")

except Exception as e:
    print(f"❌ ERROR: {e}")
