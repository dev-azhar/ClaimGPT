import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # This will automatically pull DATABASE_URL from your environment variables
    database_url: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"
    )
    
    # You can add other global settings here later (MinIO, Celery, etc.)
    app_name: str = "ClaimGPT-Core"

settings = Settings()