
import pyodbc

from config.settings import settings


def get_connection():
    """
    Establish a SQL Server connection using
    Windows Authentication.
    """

    connection_string = (
        f"DRIVER={{{settings.DB_DRIVER}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE={settings.DB_NAME};"
        f"Trusted_Connection={settings.DB_TRUSTED_CONNECTION};"
        f"Encrypt={settings.DB_ENCRYPT};"
        f"TrustServerCertificate="
        f"{settings.DB_TRUST_SERVER_CERTIFICATE};"
        f"Connection Timeout={settings.DB_TIMEOUT};"
    )

    return pyodbc.connect(connection_string)
