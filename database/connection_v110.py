import pyodbc

from config.settings import settings


TARGET_DATABASE = "ExamSchedulingDB_v110"


def get_connection_v110():
    """
    Establish a read/write-capable SQL Server connection specifically
    to ExamSchedulingDB_v110.

    This function does not modify the default database configuration.
    The scheduling repository will use it for read-only data loading.
    """

    connection_string = (
        f"DRIVER={{{settings.DB_DRIVER}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE={TARGET_DATABASE};"
        f"Trusted_Connection={settings.DB_TRUSTED_CONNECTION};"
        f"Encrypt={settings.DB_ENCRYPT};"
        f"TrustServerCertificate="
        f"{settings.DB_TRUST_SERVER_CERTIFICATE};"
        f"Connection Timeout={settings.DB_TIMEOUT};"
    )

    return pyodbc.connect(connection_string)