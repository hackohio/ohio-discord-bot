import tempfile
from pathlib import Path
import unittest

from tests import _TEST_DATABASE

import records


class DatabaseTestMixin:
    def setUp(self):
        super().setUp()
        self._database_directory = tempfile.TemporaryDirectory()
        records._DATABASE_FILE = str(
            Path(self._database_directory.name) / "records.db"
        )
        records._initialize_db()

    def tearDown(self):
        records._DATABASE_FILE = _TEST_DATABASE
        self._database_directory.cleanup()
        super().tearDown()

    def add_verified(
        self,
        discord_id,
        email=None,
        *,
        username=None,
        is_capstone=False,
        is_professional=False,
        roles=None,
    ):
        email = email or f"user{discord_id}@example.com"
        username = username or f"user-{discord_id}"
        records.add_registration(
            email,
            "Test",
            "User",
            is_capstone,
            roles if roles is not None else ["participant"],
            is_professional=is_professional,
        )
        records.add_verified_user(email, discord_id, username)
        return email


class DatabaseTestCase(DatabaseTestMixin, unittest.TestCase):
    pass
