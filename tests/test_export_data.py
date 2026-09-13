import csv
from pathlib import Path
import tempfile
from unittest.mock import patch

from tests.helpers import DatabaseTestCase

import export_data


class ExportDataTestCase(DatabaseTestCase):
    def test_team_data_has_stable_order_and_padded_members(self):
        self.add_verified(101, email="one@example.com", username="one#0001")
        self.add_verified(102, email="two@example.com", username="two#0001")
        first_team = export_data.records.create_team("Zeta", False, 201, 202, 203)
        second_team = export_data.records.create_team("Alpha", False, 204, 205, 206)
        export_data.records.join_team(101, first_team)
        export_data.records.join_team(102, first_team)

        data = export_data.get_team_data()

        self.assertEqual(
            data,
            [
                ["Team ID", "Team Name", "Member 1 Email", "Member 2 Email"],
                [first_team, "Zeta", "one@example.com", "two@example.com"],
                [second_team, "Alpha", "", ""],
            ],
        )

    def test_export_writes_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "teams.csv"
            export_data.export_to_csv(str(destination), [["header"], ["value"]])
            with destination.open(newline="", encoding="utf-8") as csv_file:
                self.assertEqual(list(csv.reader(csv_file)), [["header"], ["value"]])

    def test_failed_replace_preserves_previous_export_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "teams.csv"
            destination.write_text("old export\n", encoding="utf-8")

            with patch.object(export_data.os, "replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    export_data.export_to_csv(str(destination), [["new export"]])

            self.assertEqual(destination.read_text(encoding="utf-8"), "old export\n")
            self.assertEqual(list(destination.parent.glob(".teams.csv.*.tmp")), [])
