from django.test import SimpleTestCase

from dispatcharr.settings import celery_broker_url_from_redis_url


class CeleryBrokerUrlFromRedisUrlTests(SimpleTestCase):
    """REDIS_URL must convert into a broker URL that Kombu can actually parse.

    Kombu's redis transport accepts redis:// and rediss:// URLs unchanged
    (db from the path or a db= query key). Unix sockets need Celery's own
    redis+socket:// convention with virtual_host= instead of db=. Renaming
    db= to virtual_host= on a non-unix URL would leave both a path-derived
    virtual_host and a virtual_host= query key, which crashes Kombu's URL
    parser.
    """

    def test_tcp_url_passes_through_unchanged(self):
        url = "redis://user:secret@localhost:6379/3"
        self.assertEqual(celery_broker_url_from_redis_url(url), url)

    def test_tcp_url_with_query_string_db_passes_through_unchanged(self):
        url = "redis://cache.example.com:6379?db=2"
        self.assertEqual(celery_broker_url_from_redis_url(url), url)

    def test_rediss_url_passes_through_unchanged(self):
        url = "rediss://localhost:6379/0?ssl_cert_reqs=none"
        self.assertEqual(celery_broker_url_from_redis_url(url), url)

    def test_unix_url_renames_db_to_virtual_host(self):
        url = "unix:///var/run/redis/redis.sock?db=7"
        self.assertEqual(
            celery_broker_url_from_redis_url(url),
            "redis+socket:///var/run/redis/redis.sock?virtual_host=7",
        )

    def test_unix_url_without_db_has_no_virtual_host_key(self):
        url = "unix:///var/run/redis/redis.sock"
        self.assertEqual(
            celery_broker_url_from_redis_url(url),
            "redis+socket:///var/run/redis/redis.sock",
        )

    def test_unix_result_is_kombu_parseable(self):
        """Regression guard: a scheme-blind db->virtual_host rename produces a
        URL that crashes Kombu's parser with duplicate virtual_host values."""
        from kombu import Connection

        url = celery_broker_url_from_redis_url("unix:///var/run/redis/redis.sock?db=7")
        conn = Connection(url)
        self.assertEqual(conn.transport_cls, "redis")

    def test_password_containing_db_substring_is_not_mangled(self):
        """A scheme-blind, substring-based db->virtual_host rename would corrupt
        credentials that happen to contain the literal text "db=" (e.g. inside a
        password). Renaming only the exact "db" query key for unix:// avoids that."""
        url = "redis://user:paSSdb=1234@localhost:6379/0"
        self.assertEqual(celery_broker_url_from_redis_url(url), url)
