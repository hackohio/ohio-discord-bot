from pathlib import Path
from unittest.mock import patch

from tests.helpers import DatabaseTestCase

import config
import records
import web


class WebhookTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = web.app.test_client()
        self.headers = {"api-key": config.web_api_key}

    def post(self, payload, **kwargs):
        return self.client.post(
            "/post/user", json=payload, headers=self.headers, **kwargs
        )

    def test_health_endpoint_requires_discord_readiness(self):
        ready_file = Path(self._database_directory.name) / "discord-ready"
        with patch.object(web.config, "discord_ready_file", str(ready_file)):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json, {"status": "starting"})

            ready_file.touch()
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"status": "ready"})

    def test_invalid_api_key_returns_401(self):
        response = self.client.post(
            "/post/user", json={}, headers={"api-key": "wrong-key"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "API-Key is not correct.")

    def test_oversized_request_returns_json_413(self):
        response = self.post({"email": "person@example.com", "extra": "x" * 16384})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json, {"error": "Request body must not exceed 16 KiB"}
        )

    def test_invalid_json_and_fields_return_400(self):
        response = self.client.post(
            "/post/user", data="not json", headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

        for payload in (
            {},
            {"email": "person@example.com", "roles": ["1"]},
            {"email": "person@example.com", "is_capstone": "true"},
        ):
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)

    def test_email_is_normalized_and_missing_roles_default_to_participant(self):
        response = self.post(
            {
                "email": " Person @ Example.COM ",
                "first_name": "Pat",
                "last_name": "One",
                "is_capstone": True,
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["email"], "person@example.com")
        self.assertEqual(response.json["roles"], ["participant"])
        registration = records.get_registration("person@example.com")
        self.assertEqual(records.get_user_roles("person@example.com"), ["participant"])
        self.assertTrue(registration["is_capstone"])

    def test_professional_registration_and_category_validation(self):
        response = self.post(
            {
                "email": "professional@example.com",
                "is_professional": True,
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["is_professional"])
        self.assertTrue(
            records.get_registration("professional@example.com")["is_professional"]
        )

        response = self.post(
            {"email": "invalid@example.com", "is_professional": "true"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("is_professional", response.json["error"])

        response = self.post(
            {
                "email": "both@example.com",
                "is_capstone": True,
                "is_professional": True,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot both be true", response.json["error"])
        self.assertIsNone(records.get_registration("both@example.com"))

    def test_judge_and_mentor_role_codes_are_mapped(self):
        response = self.post(
            {
                "email": "staff@example.com",
                "roles": "1, 2, 1, unknown",
                "is_capstone": False,
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["roles"], ["judge", "mentor"])
        self.assertEqual(
            records.get_user_roles("staff@example.com"), ["judge", "mentor"]
        )

    def test_database_error_returns_generic_500(self):
        with patch.object(
            web.records, "add_registration", side_effect=RuntimeError("private data")
        ):
            response = self.post(
                {"email": "person@example.com", "first_name": "Pat"}
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {"error": "An internal server error occurred."})
        self.assertNotIn("private data", response.get_data(as_text=True))
