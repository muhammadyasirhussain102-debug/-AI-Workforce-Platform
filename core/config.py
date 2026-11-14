import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Employee Management & Agentic RAG"
    
    # Database connection string
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql+asyncpg://postgres:postgres@localhost:5432/workforce"
    )
    
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-prod")
    APP_ENV: str = os.getenv("APP_ENV", "development")

    class Config:
        case_sensitive = True

settings = Settings()