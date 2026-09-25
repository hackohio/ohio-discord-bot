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

        missing_headers = self.write_csv(
            ["Progress", "Email", "First Name", "Last Name"], []
        )
        with self.assertRaisesRegex(ValueError, "Capstone Team"):
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

    def test_missing_or_blank_professional_field_defaults_to_false(self):
        base_row = {
            "Progress": "100",
            "First Name": "Standard",
            "Last Name": "User",
            "Capstone Team": "No",
        }
        cases = (
            (PARTICIPANT_FIELDS[:-1], base_row | {"Email": "missing@example.com"}),
            (
                PARTICIPANT_FIELDS,
                base_row | {"Email": "blank@example.com", "is_professional": ""},
            ),
        )
        for fields, row in cases:
            path = self.write_csv(fields, [row], name=row["Email"] + ".csv")
            import_table.import_file(str(path))
            self.assertFalse(records.get_registration(row["Email"])["is_professional"])

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
            ["Progress", "Email", "First Name", "Last Name", "Roles"],
            [
                {
                    "Progress": "100",
                    "Email": "judge@example.com",
                    "First Name": "Judge",
                    "Last Name": "Person",
                    "Roles": "1",
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
        self.assertEqual(records.get_user_roles("mentor@example.com"), ["mentor"])
