
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    DB_DRIVER = os.getenv(
        "DB_DRIVER", "ODBC Driver 18 for SQL Server"
    )

    DB_SERVER = os.getenv("DB_SERVER")
    DB_NAME = os.getenv("DB_NAME", "ExamSchedulingDB")

    DB_TRUSTED_CONNECTION = os.getenv(
        "DB_TRUSTED_CONNECTION", "yes"
    )

    DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")
    DB_TRUST_SERVER_CERTIFICATE = os.getenv(
        "DB_TRUST_SERVER_CERTIFICATE", "yes"
    )

    DB_TIMEOUT = int(os.getenv("DB_TIMEOUT", "15"))

    RANDOM_SEED = 20261022

    if not DB_SERVER:
        raise RuntimeError("DB_SERVER is missing from .env")


settings = Settings()
