import csv
import os

import records

# For all teams in the teamDB, get teamName and all users associated with it
# TeamData = [Team ID, TeamName, Members...]

TEAM_EXPORT_FILENAME = "team_export.csv"
VERIFIED_PARTICIPANTS_FILENAME = "verified_participants.csv"


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


def get_verified_participant_data():
    headers = ["First Name", "Last Name", "Email"]
    participants = sorted(
        records.get_verified_participants(),
        key=lambda participant: participant["email"],
    )
    rows = [
        [participant["first_name"], participant["last_name"], participant["email"]]
        for participant in participants
    ]
    return [headers] + rows


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

def main():
    export_to_csv(TEAM_EXPORT_FILENAME, get_team_data())
    export_to_csv(
        VERIFIED_PARTICIPANTS_FILENAME,
        get_verified_participant_data(),
    )


if __name__ == "__main__":
    main()
