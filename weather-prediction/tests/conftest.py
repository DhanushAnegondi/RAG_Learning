"""Tests run against a real Postgres: the Compose service's `weatherwise_test` database.

Start it with `make up`. Each `fresh_db()` call returns a migrated, emptied database.
"""

import os

from weatherwise import warehouse

TEST_URL = os.environ.get(
    "WEATHERWISE_TEST_DATABASE_URL",
    "postgresql://weatherwise:weatherwise@127.0.0.1:15480/weatherwise_test",
)


def fresh_db():
    con = warehouse.connect(TEST_URL)
    warehouse.reset(con)
    return con
