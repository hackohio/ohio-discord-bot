# OHI/O Discord Bot

The OHI/O Discord Bot supports hackathon registration, Discord account
verification, role assignment, and team formation. It also exposes a small,
API-key-protected webhook for keeping the local registration database in sync
with event intake workflows.

## What it does

- Verifies registered attendees by email and assigns participant, mentor, judge,
  verified, and all-access roles.
- Lets participants create, manage, and inspect hackathon teams, including
  private team channels and roles.
- Gives organizers commands for manual verification, team removal, channel
  lookup, and team-wide broadcasts.
- Accepts registration updates at `POST /post/user` and stores data in the local
  SQLite database (`records.db`).

## Run locally

This project requires Python 3.12 and an organization-provided
`config.ini` in the repository root. The file contains Discord, email, and
webhook credentials; keep it private and never commit it.

```bash
python -m venv venv
source venv/bin/activate  # Windows (cmd.exe): venv\Scripts\activate.bat
pip install -r requirements.txt
python start.py
```

`start.py` launches the Discord bot and the webhook server as separate
processes. Stop both with `Ctrl+C`.

## Configuration

Ask the OHI/O tech lead for the current `config.ini` from the shared
organization folder. It must define these sections and values:

| Section   | Required values                                                |
| --------- | -------------------------------------------------------------- |
| `discord` | `guild_id`, `token`, channel and role IDs, `shared_categories` |
| `contact` | `registration_link`, `organizer_email`                         |
| `web`     | `port`, `api_key`                                              |
| `email`   | `address`, `password`, `code_expiration_time`                  |

The webhook expects an `api-key` header that matches the configured key. Its
JSON body includes `email`, `first_name`, `last_name`, `is_capstone`, and an
optional comma-separated `roles` value; role codes `1` and `2` map to judge and
mentor, respectively.

## Project layout

| File                                 | Purpose                                                          |
| ------------------------------------ | ---------------------------------------------------------------- |
| [`start.py`](start.py)               | Starts the bot and webhook processes.                            |
| [`bot.py`](bot.py)                   | Discord slash commands, verification, roles, and team workflows. |
| [`web.py`](web.py)                   | Registration webhook.                                            |
| [`records.py`](records.py)           | SQLite schema and data access functions.                         |
| [`import_table.py`](import_table.py) | Imports Qualtrics CSV exports.                                   |
| [`export_data.py`](export_data.py)   | Exports team data to CSV.                                        |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete local setup,
fork-and-pull-request workflow, and learning resources.
