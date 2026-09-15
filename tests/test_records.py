import sqlite3
from unittest.mock import patch

from tests.helpers import DatabaseTestCase

import records


class RecordsTestCase(DatabaseTestCase):
    def test_registration_upsert_roles_queries_and_cascade(self):
        records.add_registration(
            "person@example.com",
            "Pat",
            "One",
            True,
            ["participant", "judge", "mentor"],
        )
        registration = records.get_registration("person@example.com")
        self.assertEqual(registration["first_name"], "Pat")
        self.assertEqual(registration["last_name"], "One")
        self.assertEqual(registration["is_capstone"], 1)
        self.assertEqual(
            records.get_user_roles("person@example.com"),
            ["participant", "judge", "mentor"],
        )

        records.add_registration(
            "person@example.com", "Updated", "Name", False, ["mentor"]
        )
        self.assertEqual(
            records.get_registration("person@example.com"),
            {
                "email": "person@example.com",
                "first_name": "Updated",
                "last_name": "Name",
                "is_capstone": 0,
                "is_participant": 0,
                "is_judge": 0,
                "is_mentor": 1,
            },
        )
        records.add_registration(
            "other@example.com", "Other", "Person", False, ["participant"]
        )
        records.update_roles("person@example.com", ["participant", "judge"])
        self.assertEqual(
            records.get_user_roles("person@example.com"), ["participant", "judge"]
        )
        self.assertEqual(records.get_user_roles("missing@example.com"), [])
        self.assertIsNone(records.get_registration("missing@example.com"))
        self.assertEqual(
            {row["email"] for row in records.get_all_registrants()},
            {"person@example.com", "other@example.com"},
        )
        self.assertEqual(
            [row["email"] for row in records.get_all_registrants("judge")],
            ["person@example.com"],
        )
        self.assertEqual(
            {row["email"] for row in records.get_all_registrants("participant")},
            {"other@example.com", "person@example.com"},
        )

        records.add_verified_user("person@example.com", 101, "pat#0001")
        records.remove_registration("person@example.com")
        self.assertFalse(records.is_registered("person@example.com"))
        self.assertFalse(records.is_verified(101))

    def test_unregistered_email_cannot_be_verified(self):
        with self.assertRaises(sqlite3.IntegrityError):
            records.add_verified_user("missing@example.com", 101, "missing#0001")
        self.assertFalse(records.is_verified(101))

    def test_verified_lookup_removal_and_same_email_is_noop(self):
        self.add_verified(101, email="person@example.com", username="person#0001")
        records.add_verified_user("person@example.com", 202, "replacement#0001")

        self.assertEqual(records.get_verified_email(101), "person@example.com")
        self.assertIsNone(records.get_verified_email(202))
        self.assertTrue(records.is_verified("person@example.com"))
        self.assertEqual(records.get_verified_user(101)["username"], "person#0001")
        self.assertEqual(
            records.get_verified_user("person@example.com")["discord_id"], 101
        )

        records.remove_verified_user("person@example.com")
        self.assertFalse(records.is_verified(101))
        self.assertIsNone(records.get_verified_user(101))

    def test_verified_discord_id_and_username_are_unique(self):
        self.add_verified(101, email="one@example.com", username="one#0001")
        self.add_verified(102, email="two@example.com", username="two#0001")
        records.add_registration(
            "three@example.com", "Three", "User", False, ["participant"]
        )

        with self.assertRaises(sqlite3.IntegrityError):
            records.add_verified_user("three@example.com", 101, "three#0001")
        with self.assertRaises(sqlite3.IntegrityError):
            records.add_verified_user("three@example.com", 103, "one#0001")

    def test_team_creation_membership_lead_and_removal(self):
        self.add_verified(101, email="one@example.com", username="one#0001")
        self.add_verified(102, email="two@example.com", username="two#0001")
        team_id = records.create_team("Team One", False, 201, 202, 203, 204)

        self.assertEqual(records.get_team(team_id)["name"], "Team One")
        self.assertEqual(records.get_team("Team One")["id"], team_id)
        self.assertTrue(records.team_exists(team_id))
        self.assertTrue(records.team_exists("Team One"))
        self.assertEqual(records.get_team_size(team_id), 0)

        records.join_team(101, team_id)
        records.join_team(102, team_id)
        self.assertEqual(records.get_user_team_id(101), team_id)
        self.assertEqual(records.get_user_team_id("two@example.com"), team_id)
        self.assertEqual(records.get_team_size("Team One"), 2)
        self.assertEqual(
            {member["discord_id"] for member in records.get_team_members("Team One")},
            {101, 102},
        )

        records.set_team_lead(team_id, 101)
        self.assertEqual(records.get_team(team_id)["team_lead"], 101)
        records.remove_team_lead(team_id)
        self.assertIsNone(records.get_team(team_id)["team_lead"])

        records.remove_team(team_id)
        self.assertFalse(records.team_exists("Team One"))
        self.assertIsNone(records.get_user_team_id(101))
        self.assertIsNone(records.get_user_team_id(102))

    def test_next_team_id_follows_autoincrement_after_deletion(self):
        first = records.create_team("First", False, 1, 2, 3)
        records.remove_team(first)
        self.assertEqual(records.get_next_team_id(), first + 1)
        self.assertEqual(records.create_team("Second", False, 4, 5, 6), first + 1)
        self.assertEqual(records.get_max_team_id(), first + 1)
        self.assertEqual(len(records.get_all_teams()), 1)

    @patch("records.time.time", return_value=100.0)
    def test_code_is_valid_before_expiration_and_invalid_at_boundary(self, _time):
        records.add_code("person@example.com", 101, "123456", 10)
        self.assertTrue(records.code_exists("123456"))
        self.assertEqual(records.get_value_from_code("123456")["expires_at"], 110.0)

        _time.return_value = 110.0
        self.assertIsNone(records.get_value_from_code("123456"))
        # code_exists reports storage presence; verification uses the
        # expiration-aware get_value_from_code lookup.
        self.assertTrue(records.code_exists("123456"))

    @patch("records.time.time", return_value=100.0)
    def test_code_replacement_conflicts_by_code_email_and_discord_id(self, _time):
        records.add_code("one@example.com", 101, "111111", 60)
        records.add_code("two@example.com", 102, "111111", 60)
        self.assertTrue(records.code_exists("111111"))
        self.assertEqual(
            records.get_value_from_code("111111")["email"], "two@example.com"
        )
        self.assertEqual(records.get_value_from_code("two-does-not-exist"), None)

        records.add_code("two@example.com", 102, "222222", 60)
        self.assertFalse(records.code_exists("111111"))
        self.assertTrue(records.code_exists("222222"))
        records.add_code("three@example.com", 102, "333333", 60)
        self.assertFalse(records.code_exists("222222"))
        self.assertEqual(
            records.get_value_from_code("333333")["email"], "three@example.com"
        )

    def test_category_stack_returns_latest_value(self):
        self.assertIsNone(records.get_latest_category())
        records.push_new_category(201)
        records.push_new_category(202)
        self.assertEqual(records.get_latest_category(), 202)

    def test_lfg_pool_adds_updates_filters_team_members_and_removes(self):
        records.add_registration(
            "one@example.com", "Alice", "One", False, ["participant"]
        )
        records.add_verified_user("one@example.com", 101, "alice#0001")
        self.add_verified(102)

        records.add_to_lfg(101, "Python")
        records.add_to_lfg(101, "Rust")
        records.add_to_lfg(102)
        team_id = records.create_team("Team", False, 201, 202, 203)
        records.join_team(102, team_id)

        self.assertTrue(records.is_looking(101))
        self.assertTrue(records.is_looking(102))
        self.assertEqual(
            records.get_lfg_list(),
            [
                {
                    "discord_id": 101,
                    "username": "alice#0001",
                    "first_name": "Alice",
                    "skills": "Rust",
                }
            ],
        )

        records.remove_from_lfg(101)
        records.remove_from_lfg(101)
        self.assertFalse(records.is_looking(101))

    def test_lfg_pool_requires_verification_and_cascades_on_registration_removal(self):
        with self.assertRaises(sqlite3.IntegrityError):
            records.add_to_lfg(999, "Python")

        self.add_verified(101, email="person@example.com")
        records.add_to_lfg(101, "Python")
        records.remove_registration("person@example.com")
        self.assertFalse(records.is_looking(101))

    def test_team_grace_period_persists_and_clears(self):
        team_id = records.create_team("Team", False, 201, 202, 203)

        records.set_grace_period(team_id, 400.0)
        self.assertEqual(records.get_team(team_id)["grace_period"], 400.0)
        self.assertEqual(
            records.get_all_grace_periods(),
            [{"id": team_id, "name": "Team", "grace_period": 400.0}],
        )

        records.clear_grace_period(team_id)
        self.assertEqual(records.get_all_grace_periods(), [])

    def test_legacy_teams_table_gets_grace_period_column(self):
        legacy_database = self._database_directory.name + "/legacy-teams.db"
        records._DATABASE_FILE = legacy_database
        with sqlite3.connect(records._DATABASE_FILE) as connection:
            connection.execute(
                """
                CREATE TABLE teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    is_capstone BOOLEAN DEFAULT 0,
                    team_lead INTEGER,
                    role_id INTEGER NOT NULL,
                    category_id INTEGER NOT NULL,
                    text_id INTEGER NOT NULL,
                    voice_id INTEGER
                )
                """
            )

        records._initialize_db()
        with records._get_connection() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(teams)")
            }
        self.assertIn("grace_period", columns)

    def test_legacy_codes_table_gets_expiration_column(self):
        legacy_database = self._database_directory.name + "/legacy.db"
        records._DATABASE_FILE = legacy_database
        with sqlite3.connect(records._DATABASE_FILE) as connection:
            connection.execute(
                """
                CREATE TABLE codes (
                    code TEXT PRIMARY KEY,
                    discord_id INTEGER UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO codes(code, discord_id, email) VALUES (?, ?, ?)",
                ("old-code", 101, "old@example.com"),
            )

        records._initialize_db()
        with records._get_connection() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(codes)")
            }
            expiration = connection.execute(
                "SELECT expires_at FROM codes WHERE code = 'old-code'"
            ).fetchone()[0]
        self.assertIn("expires_at", columns)
        self.assertEqual(expiration, 0)
        self.assertIsNone(records.get_value_from_code("old-code"))
