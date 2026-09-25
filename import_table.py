"""Import Qualtrics registration CSV data into the event database."""

import csv
import logging
import sys
import time
from pathlib import Path

import records
from logging_config import configure_logging

JUDGE_ROLE_NUM = "1"
MENTOR_ROLE_NUM = "2"
logger = logging.getLogger(__name__)


def import_file(source_filename: str) -> dict:
    """Import one registration CSV and return its totals."""
    started_at = time.monotonic()
    source_path = Path(source_filename)
    totals = {
        "entries": 0,
        "inserted": 0,
        "updated": 0,
        "duplicate": 0,
        "unfinished": 0,
        "missing_email": 0,
        "missing_role": 0,
    }
    logger.info("import_started source=%r", source_filename)

    if source_path.suffix.lower() != ".csv":
        raise ValueError("Not a CSV file. Check format and resubmit.")

    with source_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fields = set(reader.fieldnames or ())
        required = {"Progress", "Email", "First Name", "Last Name"}
        if not required.issubset(fields):
            raise ValueError(
                f"CSV file missing required attributes: {', '.join(sorted(required - fields))}"
            )

        is_participant = "Roles" not in fields
        if is_participant and "Capstone Team" not in fields:
            raise ValueError("CSV file missing required attribute: Capstone Team")

        for row_number, entry in enumerate(reader, start=2):
            totals["entries"] += 1
            try:
                if entry.get("Progress") != "100":
                    totals["unfinished"] += 1
                    continue

                email = entry.get("Email", "").replace(" ", "").lower()
                if not email:
                    totals["missing_email"] += 1
                    continue

                if is_participant:
                    professional_value = entry.get("is_professional")
                    if professional_value not in {None, "", "Yes", "No"}:
                        raise ValueError("is_professional must be Yes or No")
                    is_capstone = entry.get("Capstone Team") == "Yes"
                    is_professional = professional_value == "Yes"
                    roles = ["participant"]
                else:
                    is_capstone = False
                    is_professional = False
                    role_input = entry.get("Roles") or ""
                    roles = []
                    if JUDGE_ROLE_NUM in role_input:
                        roles.append("judge")
                    if MENTOR_ROLE_NUM in role_input:
                        roles.append("mentor")
                    if not roles:
                        totals["missing_role"] += 1
                        continue

                existing = records.get_registration(email)
                if existing and (
                    existing["first_name"] == entry["First Name"]
                    and existing["last_name"] == entry["Last Name"]
                    and existing["is_capstone"] == is_capstone
                    and existing["is_professional"] == is_professional
                    and set(records.get_user_roles(email)) == set(roles)
                ):
                    totals["duplicate"] += 1
                    continue

                outcome = "updated" if existing else "inserted"
                records.add_registration(
                    email,
                    entry["First Name"],
                    entry["Last Name"],
                    is_capstone,
                    roles,
                    is_professional=is_professional,
                )
                totals[outcome] += 1
            except Exception as exc:
                exc.add_note(f"CSV row {row_number} in {source_filename!r}")
                raise

    totals["duration_ms"] = round((time.monotonic() - started_at) * 1000, 3)
    logger.info("import_completed source=%r totals=%r", source_filename, totals)
    return totals


def main(argv: list[str] | None = None) -> int:
    configure_logging("import")
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("USAGE: import_table.py [csv_filename]")
        return 2

    source_filename = argv[0]
    print(f"Started importing {source_filename}, please wait...")
    try:
        totals = import_file(source_filename)
    except Exception as exc:
        logger.exception("import_failed source=%r", source_filename)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = totals["entries"]
    added = totals["inserted"] + totals["updated"]
    print(f"Finished importing {source_filename}")
    print(f"Processing time: {totals['duration_ms'] / 1000:.3f} seconds")
    print(f"Total number of entries processed: {entries}")
    print("-----------------------------------------")
    print(f"Number of entries added to database: {added} out of {entries}")
    print(f"Number of duplicate entries: {totals['duplicate']} out of {entries}")
    incomplete = totals["missing_email"] + totals["missing_role"]
    print(
        f"Number of entries with incomplete information: {incomplete} out of {entries}"
    )
    print(f"Number of unfinished entries: {totals['unfinished']} out of {entries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
