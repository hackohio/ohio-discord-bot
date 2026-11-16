# OHI/O Discord Bot

The OHI/O Discord Bot supports hackathon registration, Discord account
verification, role assignment, and team formation. It also exposes a small,
API-key-protected webhook for keeping the local registration database in sync
with event intake workflows.

## What it does

- Verifies registered attendees by email and assigns participant, mentor, judge,
  sponsor, verified, and all-access roles.
- Lets participants create, manage, and inspect hackathon teams, including
  private team channels and roles.
- Gives organizers commands for manual verification, team removal, channel
  lookup, and team-wide broadcasts.
- Accepts registration updates at `POST /post/user` and stores data in the local
  SQLite database (`records.db`).

## Run locally

This project requires Python 3.12, [uv](https://docs.astral.sh/uv/), and an
organization-provided `config.ini` in the repository root. The file contains
Discord, email, and webhook credentials; keep it private and never commit it.

```bash
uv sync
uv run python start.py
```

`uv sync` creates the project environment and installs the exact dependency
versions recorded in `uv.lock`. Use `uv sync --locked` to verify that the lock
file is current without changing it.

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

The Discord role IDs must include `sponsor_role_id`.

The webhook expects an `api-key` header that matches a configured key of at
least 32 characters. Generate one with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Its JSON body
includes `email`, `first_name`, `last_name`, `is_capstone`, optional
`is_professional` and `is_sponsor` booleans, and an optional comma-separated
`roles` value. The category flags cannot both be true; omitted optional booleans
default to `false`. Role codes `1` and `2` map to judge and mentor, respectively.
The bot needs Manage Roles permission, and its highest role must be above the
sponsor role. CSV imports accept optional `Capstone Team`, `is_professional`,
and `is_sponsor` columns with `Yes` or `No` values. Missing or blank values
preserve the existing database flags; new registrations default to `false`.
Capstone and professional cannot both be true, so switching categories requires
an explicit `No` for the previous category. `/overify` accepts optional
`is_capstone`, `is_professional`, and `is_sponsor` flags: omit them to preserve
existing status, or supply `true` or `false` to update them, including for
already-verified users. New registrations default to `false`. The database
upsert overwrites supplied values; CSV and `/overify` resolve omitted flags
before calling it, while webhook resubmissions overwrite existing flags.
Deployed requests use HTTPS; the internal Waitress port is loopback-only.

## Project layout

| File                                       | Purpose                                        |
| ------------------------------------------ | ---------------------------------------------- |
| [`start.py`](start.py)                     | Starts the bot and webhook processes.          |
| [`discord_bot/app.py`](discord_bot/app.py) | Bot lifecycle, intents, and extension loading. |
| [`discord_bot/cogs/`](discord_bot/cogs/)   | Discord commands grouped by event workflow.    |
| [`web.py`](web.py)                         | Registration webhook.                          |
| [`records.py`](records.py)                 | SQLite schema and data access functions.       |
| [`import_table.py`](import_table.py)       | Imports Qualtrics CSV exports.                 |
| [`export_data.py`](export_data.py)         | Exports team data to CSV.                      |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete local setup,
fork-and-pull-request workflow, and learning resources.
