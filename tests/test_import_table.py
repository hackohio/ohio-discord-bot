import csv
from pathlib import Path

from tests.helpers import DatabaseTestCase

import import_table
import records


PARTICIPANT_FIELDS = [
    "Progress",
    "Email",
    "First Name",
    "Last Name",
    "Capstone Team",
    "is_professional",
]


class ImportTableTestCase(DatabaseTestCase):
    def write_csv(self, fields, rows, name="registrations.csv"):
        path = Path(self._database_directory.name) / name
        with path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_wrong_extension_and_missing_headers_are_rejected(self):
        wrong_extension = self.write_csv(
            ["Progress", "Email"], [], name="registrations.txt"
        )
        with self.assertRaisesRegex(ValueError, "Not a CSV"):
            import_table.import_file(str(wrong_extension))

        missing_headers = self.write_csv(["Progress", "Email", "First Name"], [])
        with self.assertRaisesRegex(ValueError, "Last Name"):
            import_table.import_file(str(missing_headers))

    def test_participant_import_totals_and_normalized_data(self):
        path = self.write_csv(
            PARTICIPANT_FIELDS,
            [
                {
                    "Progress": "50",
                    "Email": "unfinished@example.com",
                    "First Name": "Un",
                    "Last Name": "Finished",
                    "Capstone Team": "No",
                    "is_professional": "No",
                },
                {
                    "Progress": "100",
                    "Email": " ",
                    "First Name": "Missing",
                    "Last Name": "Email",
                    "Capstone Team": "No",
                    "is_professional": "No",
                },
                {
                    "Progress": "100",
                    "Email": " New @Example.com ",
                    "First Name": "New",
                    "Last Name": "Person",
                    "Capstone Team": "Yes",
                    "is_professional": "No",
                },
                {
                    "Progress": "100",
                    "Email": "new@example.com",
                    "First Name": "New",
                    "Last Name": "Person",
                    "Capstone Team": "Yes",
                    "is_professional": "No",
                },
                {
                    "Progress": "100",
                    "Email": "new@example.com",
                    "First Name": "Updated",
                    "Last Name": "Person",
                    "Capstone Team": "No",
                    "is_professional": "No",
                },
            ],
        )
        totals = import_table.import_file(str(path))

        self.assertEqual(totals["entries"], 5)
        self.assertEqual(totals["unfinished"], 1)
        self.assertEqual(totals["missing_email"], 1)
        self.assertEqual(totals["inserted"], 1)
        self.assertEqual(totals["duplicate"], 1)
        self.assertEqual(totals["updated"], 1)
        self.assertEqual(
            records.get_registration("new@example.com")["first_name"], "Updated"
        )
        self.assertFalse(records.get_registration("new@example.com")["is_capstone"])
        self.assertEqual(records.get_user_roles("new@example.com"), ["participant"])

    def test_missing_or_blank_flags_preserve_existing_status_and_count_duplicates(self):
        for staff in (False, True):
            for omitted in (None, "", " \t"):
                for capstone, professional, sponsor in (
                    (True, False, True),
                    (False, True, True),
                    (False, False, False),
                ):
                    with self.subTest(
                        staff=staff,
                        omitted=omitted,
                        capstone=capstone,
                        professional=professional,
                        sponsor=sponsor,
                    ):
                        email = "existing@example.com"
                        records.add_registration(
                            email,
                            "Old",
                            "Name",
                            capstone,
                            ["judge"] if staff else ["participant"],
                            is_professional=professional,
                            is_sponsor=sponsor,
                        )
                        row = {
                            "Progress": "100",
                            "Email": email,
                            "First Name": "Updated",
                            "Last Name": "Name",
                        }
                        if staff:
                            row["Roles"] = "1"
                        if omitted is not None:
                            row.update(
                                {
                                    "Capstone Team": omitted,
                                    "is_professional": omitted,
                                    "is_sponsor": omitted,
                                }
                            )
                        path = self.write_csv(list(row), [row])
                        totals = import_table.import_file(str(path))
                        self.assertEqual(totals["updated"], 1)
                        registration = records.get_registration(email)
                        self.assertEqual(
                            tuple(
                                registration[flag]
                                for flag in (
                                    "is_capstone",
                                    "is_professional",
                                    "is_sponsor",
                                )
                            ),
                            (capstone, professional, sponsor),
                        )
                        totals = import_table.import_file(str(path))
                        self.assertEqual(totals["duplicate"], 1)

    def test_explicit_flags_update_and_invalid_values_do_not_change_registration(self):
        for staff in (False, True):
            for column, flag in (
                ("Capstone Team", "is_capstone"),
                ("is_professional", "is_professional"),
                ("is_sponsor", "is_sponsor"),
            ):
                with self.subTest(staff=staff, column=column):
                    email = "explicit@example.com"
                    records.add_registration(
                        email,
                        "Test",
                        "User",
                        False,
                        ["judge"] if staff else ["participant"],
                    )
                    row = {
                        "Progress": "100",
                        "Email": email,
                        "First Name": "Test",
                        "Last Name": "User",
                    }
                    if staff:
                        row["Roles"] = "1"
                    for value, expected in (("Yes", True), ("No", False)):
                        row[column] = value
                        path = self.write_csv(list(row), [row])
                        totals = import_table.import_file(str(path))
                        self.assertEqual(totals["updated"], 1)
                        self.assertEqual(
                            records.get_registration(email)[flag], expected
                        )
                    before = records.get_registration(email)
                    row[column] = "Maybe"
                    path = self.write_csv(list(row), [row])
                    with self.assertRaisesRegex(
                        ValueError, f"{column} must be Yes or No"
                    ):
                        import_table.import_file(str(path))
                    self.assertEqual(records.get_registration(email), before)

    def test_preserved_category_requires_explicit_clear_when_switching_categories(self):
        email = "professional@example.com"
        records.add_registration(
            email,
            "Test",
            "User",
            False,
            ["participant"],
            is_professional=True,
        )
        row = {
            "Progress": "100",
            "Email": email,
            "First Name": "Test",
            "Last Name": "User",
            "Capstone Team": "Yes",
        }
        path = self.write_csv(list(row), [row])
        with self.assertRaisesRegex(ValueError, "cannot both be true"):
            import_table.import_file(str(path))
        self.assertTrue(records.get_registration(email)["is_professional"])
        self.assertFalse(records.get_registration(email)["is_capstone"])

        row["is_professional"] = "No"
        path = self.write_csv(list(row), [row])
        import_table.import_file(str(path))
        self.assertFalse(records.get_registration(email)["is_professional"])
        self.assertTrue(records.get_registration(email)["is_capstone"])

    def test_import_accepts_sponsor_yes_no_and_rejects_other_values(self):
        fields = PARTICIPANT_FIELDS + ["is_sponsor"]
        row = {
            "Progress": "100",
            "Email": "sponsor@example.com",
            "First Name": "Sponsor",
            "Last Name": "Person",
            "Capstone Team": "No",
            "is_professional": "No",
            "is_sponsor": "Yes",
        }
        path = self.write_csv(fields, [row])
        import_table.import_file(str(path))
        self.assertEqual(
            records.get_registration("sponsor@example.com")["is_sponsor"], 1
        )

        row["is_sponsor"] = "No"
        path = self.write_csv(fields, [row])
        totals = import_table.import_file(str(path))
        self.assertEqual(totals["updated"], 1)
        self.assertEqual(
            records.get_registration("sponsor@example.com")["is_sponsor"], 0
        )

        row["is_sponsor"] = "Maybe"
        path = self.write_csv(fields, [row], name="invalid-sponsor.csv")
        with self.assertRaisesRegex(ValueError, "is_sponsor must be Yes or No"):
            import_table.import_file(str(path))

    def test_missing_or_blank_flags_default_to_false_for_new_registrations(self):
        for staff in (False, True):
            for index, omitted in enumerate((None, "", " \t")):
                with self.subTest(staff=staff, omitted=omitted):
                    email = f"new-{staff}-{index}@example.com"
                    row = {
                        "Progress": "100",
                        "Email": email,
                        "First Name": "Test",
                        "Last Name": "User",
                    }
                    if staff:
                        row["Roles"] = "1"
                    if omitted is not None:
                        row.update(
                            {
                                "Capstone Team": omitted,
                                "is_professional": omitted,
                                "is_sponsor": omitted,
                            }
                        )
                    path = self.write_csv(list(row), [row])
                    totals = import_table.import_file(str(path))
                    self.assertEqual(totals["inserted"], 1)
                    registration = records.get_registration(
                        records.normalize_email(email)
                    )
                    for flag in ("is_capstone", "is_professional", "is_sponsor"):
                        self.assertFalse(registration[flag])

    def test_professional_import_and_invalid_category_values_are_rejected(self):
        path = self.write_csv(
            PARTICIPANT_FIELDS,
            [
                {
                    "Progress": "100",
                    "Email": "professional@example.com",
                    "First Name": "Pro",
                    "Last Name": "User",
                    "Capstone Team": "No",
                    "is_professional": "Yes",
                }
            ],
            name="professional.csv",
        )
        import_table.import_file(str(path))
        self.assertTrue(
            records.get_registration("professional@example.com")["is_professional"]
        )

        invalid_path = self.write_csv(
            PARTICIPANT_FIELDS,
            [
                {
                    "Progress": "100",
                    "Email": "invalid@example.com",
                    "First Name": "Invalid",
                    "Last Name": "User",
                    "Capstone Team": "Yes",
                    "is_professional": "Yes",
                }
            ],
            name="invalid.csv",
        )
        with self.assertRaisesRegex(ValueError, "cannot both be true"):
            import_table.import_file(str(invalid_path))

        unexpected_path = self.write_csv(
            PARTICIPANT_FIELDS,
            [
                {
                    "Progress": "100",
                    "Email": "unexpected@example.com",
                    "First Name": "Unexpected",
                    "Last Name": "User",
                    "Capstone Team": "No",
                    "is_professional": "Maybe",
                }
            ],
            name="unexpected.csv",
        )
        with self.assertRaisesRegex(ValueError, "is_professional must be Yes or No"):
            import_table.import_file(str(unexpected_path))

    def test_staff_import_maps_roles_and_counts_missing_roles(self):
        path = self.write_csv(
            [
                "Progress",
                "Email",
                "First Name",
                "Last Name",
                "Roles",
                "is_sponsor",
            ],
            [
                {
                    "Progress": "100",
                    "Email": "judge@example.com",
                    "First Name": "Judge",
                    "Last Name": "Person",
                    "Roles": "1",
                    "is_sponsor": "Yes",
                },
                {
                    "Progress": "100",
                    "Email": "mentor@example.com",
                    "First Name": "Mentor",
                    "Last Name": "Person",
                    "Roles": "2",
                },
                {
                    "Progress": "100",
                    "Email": "none@example.com",
                    "First Name": "No",
                    "Last Name": "Role",
                    "Roles": "",
                },
                {
                    "Progress": "100",
                    "Email": "unknown@example.com",
                    "First Name": "Unknown",
                    "Last Name": "Role",
                    "Roles": "3",
                },
            ],
        )
        totals = import_table.import_file(str(path))

        self.assertEqual(totals["inserted"], 2)
        self.assertEqual(totals["missing_role"], 2)
        self.assertEqual(records.get_user_roles("judge@example.com"), ["judge"])
        self.assertEqual(records.get_registration("judge@example.com")["is_sponsor"], 1)
        self.assertEqual(records.get_user_roles("mentor@example.com"), ["mentor"])
