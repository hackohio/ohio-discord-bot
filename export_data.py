import csv
import os

import pandas as pd

import records

# For all teams in the teamDB, get teamName and all users associated with it
# TeamData = [Team ID, TeamName, Members...]

EXPORT_FILENAME = "team_export.csv"


# ----------- Grab Team Data from DB ------------- #
def get_team_data():
    teams = sorted(records.get_all_teams(), key=lambda team: team["id"])
    rows: list[dict] = []
    max_members = 0

    for team in teams:
        team_members = records.get_team_members(team["id"])
        member_emails = [member["email"] for member in team_members]
        max_members = max(max_members, len(member_emails))
        rows.append(
            {
                "team_id": team["id"],
                "team_name": team["name"],
                "member_emails": member_emails,
            }
        )

    headers = ["Team ID", "Team Name"] + [
        f"Member {index} Email" for index in range(1, max_members + 1)
    ]
    team_data_list = [headers]

    for row in rows:
        team_row = [row["team_id"], row["team_name"]]
        member_values = row["member_emails"] + [""] * (
            max_members - len(row["member_emails"])
        )
        team_data_list.append(team_row + member_values)

    return team_data_list


# ----------- Export Data to CSV --------------- #
def export_to_csv(export_filename: str, data: list):
    # Remove file if it exists so it can be overwritten
    if os.path.isfile(export_filename):
        os.remove(export_filename)

    with open(export_filename, "w", newline="", encoding="utf-8") as csv_file:
        # Export Header Items
        writer = csv.writer(csv_file)

        # Add Rows of Data
        for row in data:
            writer.writerow(row)


def append_to_xlsx(export_filename: str, sheets: list[str]):
    if os.path.isfile(export_filename):
        os.remove(export_filename)

    # Create a new Excel writer object
    with pd.ExcelWriter(export_filename, engine="xlsxwriter", mode="w") as writer:
        # Write the CSV data to a new sheet
        for sheet in sheets:
            # Import csv data as sheet to excel file
            csv_file = pd.read_csv(sheet)
            csv_file.to_excel(writer, sheet_name=sheet.replace(".csv", ""), index=False)

    # Remove CSV files
    for file in sheets:
        os.remove(file)


# Retrieve Data
team_data_list = get_team_data()


# Compile into CSV
sheets = []

export_to_csv("team_export.csv", team_data_list)
sheets.append("team_export.csv")


# Compile into Excel
# append_to_xlsx('Report.xlsx', sheets)
