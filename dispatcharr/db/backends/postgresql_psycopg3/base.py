try:
    import psycopg
except ImportError as e:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Error loading psycopg3 module: %s" % e) from e

from django.db.backends.postgresql.base import DatabaseWrapper as OriginalDatabaseWrapper
from django_db_geventpool.backends.base import DatabaseWrapperMixin

from .pool import DatabaseConnectionPool


class PostgresConnectionPool(DatabaseConnectionPool):
    DBERROR = psycopg.DatabaseError

    def __init__(self, *args, **kwargs):
        self.connect = kwargs.pop("connect", psycopg.connect)
        self.connection = None
        maxsize = kwargs.pop("MAX_CONNS", 4)
        reuse = kwargs.pop("REUSE_CONNS", maxsize)
        max_lifetime = kwargs.pop("CONN_MAX_LIFETIME", None)
        self.args = args
        self.kwargs = kwargs
        self.kwargs["client_encoding"] = "UTF8"
        super().__init__(maxsize, reuse, max_lifetime=max_lifetime)

    def create_connection(self):
        return self.connect(*self.args, **self.kwargs)

    def check_usable(self, connection):
        connection.cursor().execute("SELECT 1")


class DatabaseWrapper(DatabaseWrapperMixin, OriginalDatabaseWrapper):
    pool_class = PostgresConnectionPool
    INTRANS = psycopg.pq.TransactionStatus.INTRANS

    def get_connection_params(self) -> dict:
        conn_params = super().get_connection_params()
        for attr in ("MAX_CONNS", "REUSE_CONNS", "CONN_MAX_LIFETIME"):
            if attr in self.settings_dict["OPTIONS"]:
                conn_params[attr] = self.settings_dict["OPTIONS"][attr]
        return conn_params
