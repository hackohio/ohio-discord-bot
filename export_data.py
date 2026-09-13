"""Export current team data for event organizers."""

import csv
import logging
import os
import tempfile
import time
from pathlib import Path

import records
from logging_config import configure_logging

EXPORT_FILENAME = "team_export.csv"
logger = logging.getLogger(__name__)


def get_team_data():
    teams = sorted(records.get_all_teams(), key=lambda team: team["id"])
    rows = []
    max_members = 0

    for team in teams:
        emails = [member["email"] for member in records.get_team_members(team["id"])]
        max_members = max(max_members, len(emails))
        rows.append((team["id"], team["name"], emails))

    data = [
        ["Team ID", "Team Name"]
        + [f"Member {index} Email" for index in range(1, max_members + 1)]
    ]
    for team_id, team_name, emails in rows:
        data.append([team_id, team_name] + emails + [""] * (max_members - len(emails)))
    return data


def export_to_csv(export_filename: str, data: list):
    """Write CSV atomically so failure does not corrupt an earlier export."""
    destination = Path(export_filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_name = csv_file.name
            csv.writer(csv_file).writerows(data)
        os.replace(temporary_name, destination)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    configure_logging("export")
    started_at = time.monotonic()
    logger.info("export_started destination=%r", EXPORT_FILENAME)
    try:
        team_data = get_team_data()
        export_to_csv(EXPORT_FILENAME, team_data)
    except Exception:
        logger.exception("export_failed destination=%r", EXPORT_FILENAME)
        print("ERROR: Export failed. See logs/export.log for details.")
        return 1

    team_count = len(team_data) - 1
    logger.info(
        "export_completed destination=%r team_count=%r duration_ms=%r",
        EXPORT_FILENAME,
        team_count,
        round((time.monotonic() - started_at) * 1000, 3),
    )
    print(f"Exported {team_count} teams to {EXPORT_FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
