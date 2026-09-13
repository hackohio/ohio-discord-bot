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

    def test_invalid_api_key_returns_401(self):
        response = self.client.post(
            "/post/user", json={}, headers={"api-key": "wrong-key"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "API-Key is not correct.")

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
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["email"], "person@example.com")
        self.assertEqual(response.json["roles"], ["participant"])
        self.assertEqual(
            records.get_user_roles("person@example.com"), ["participant"]
        )

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

    def test_success_persists_registration(self):
        response = self.post(
            {
                "email": "person@example.com",
                "first_name": "Pat",
                "last_name": "One",
                "roles": "1",
                "is_capstone": True,
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            records.get_registration("person@example.com"),
            {
                "email": "person@example.com",
                "first_name": "Pat",
                "last_name": "One",
                "is_capstone": 1,
                "is_participant": 0,
                "is_judge": 1,
                "is_mentor": 0,
            },
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
