import logging
import os
import sqlite3
import threading
import time
from enum import StrEnum

logger = logging.getLogger(__name__)


_DATABASE_FILE = os.environ.get("OHIO_RECORDS_DB", "records.db")
_LOCK = threading.Lock()

_REG_TABLE_NAME = "registration"
_VERIFIED_TABLE_NAME = "verified"
_TEAM_TABLE_NAME = "teams"
_CODE_TABLE_NAME = "codes"
_CATEGORY_BUCKET_NAME = "category_bucket"
_LFG_TABLE_NAME = "lfg_pool"


class ParticipantCategory(StrEnum):
    STANDARD = "standard"
    CAPSTONE = "capstone"
    PROFESSIONAL = "professional"


def get_category(
    is_capstone: bool, is_professional: bool = False
) -> ParticipantCategory:
    """Return the mutually exclusive participant category for two flags."""
    if is_capstone and is_professional:
        raise ValueError("is_capstone and is_professional cannot both be true")
    if is_capstone:
        return ParticipantCategory.CAPSTONE
    if is_professional:
        return ParticipantCategory.PROFESSIONAL
    return ParticipantCategory.STANDARD


def get_verified_category(identifier) -> ParticipantCategory:
    user = get_verified_user(identifier)
    return get_category(user["is_capstone"], user["is_professional"])


def get_team_category(identifier) -> ParticipantCategory:
    team = get_team(identifier)
    return get_category(team["is_capstone"], team["is_professional"])


def _initialize_db():

    # Lock the block of code to prevent race conditions
    with _LOCK, _get_connection() as conn:
        # Registration Table
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_REG_TABLE_NAME} (
                email TEXT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,

                is_capstone BOOLEAN NOT NULL DEFAULT 0,
                is_professional BOOLEAN NOT NULL DEFAULT 0,

                is_participant BOOLEAN DEFAULT 0,
                is_judge BOOLEAN DEFAULT 0,
                is_mentor BOOLEAN DEFAULT 0
            )
        """)

        registration_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({_REG_TABLE_NAME})")
        }
        if "is_professional" not in registration_columns:
            conn.execute(
                f"ALTER TABLE {_REG_TABLE_NAME} "
                "ADD COLUMN is_professional BOOLEAN NOT NULL DEFAULT 0"
            )

        # Verified Table
        # ON DELETE CASCADE: Deleting a Registration automatically deletes this verified user.
        # ON DELETE SET NULL: Deleting a Team just clears the user's team status, doesn't delete the user.
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_VERIFIED_TABLE_NAME} (
                email TEXT PRIMARY KEY REFERENCES {_REG_TABLE_NAME}(email) ON DELETE CASCADE,
                
                discord_id INTEGER UNIQUE,
                username TEXT UNIQUE NOT NULL,
                team_id INTEGER REFERENCES {_TEAM_TABLE_NAME}(id) ON DELETE SET NULL
            )
        """)

        # Team Table
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TEAM_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,

                is_capstone BOOLEAN NOT NULL DEFAULT 0,
                is_professional BOOLEAN NOT NULL DEFAULT 0,
                team_lead INTEGER REFERENCES {_VERIFIED_TABLE_NAME}(discord_id) ON DELETE SET NULL,

                role_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                text_id INTEGER NOT NULL,
                voice_id INTEGER,
                grace_period REAL
            )
        """)
        team_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({_TEAM_TABLE_NAME})")
        }
        if "is_professional" not in team_columns:
            conn.execute(
                f"ALTER TABLE {_TEAM_TABLE_NAME} "
                "ADD COLUMN is_professional BOOLEAN NOT NULL DEFAULT 0"
            )
        if "grace_period" not in team_columns:
            conn.execute(
                f"ALTER TABLE {_TEAM_TABLE_NAME} ADD COLUMN grace_period REAL"
            )

        # 4. CODES TABLE (Temporary Storage)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_CODE_TABLE_NAME} (
                code TEXT PRIMARY KEY,
                discord_id INTEGER UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        code_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({_CODE_TABLE_NAME})")
        }
        if "expires_at" not in code_columns:
            conn.execute(
                f"ALTER TABLE {_CODE_TABLE_NAME} "
                "ADD COLUMN expires_at REAL NOT NULL DEFAULT 0"
            )

        # 5. Category Channels Table (Only used for 1-50 category setting)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_CATEGORY_BUCKET_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL
            )
        """)

        # LFG (Looking For Group) pool: a user in this table is looking for a team
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_LFG_TABLE_NAME} (
                discord_id INTEGER PRIMARY KEY REFERENCES {_VERIFIED_TABLE_NAME}(discord_id) ON DELETE CASCADE,
                skills TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()


def _get_connection():
    """Private helper: Gets a thread-safe connection with Foreign Keys enabled."""
    conn = sqlite3.connect(_DATABASE_FILE, timeout=20)
    conn.row_factory = sqlite3.Row  # Allows dict access to db rows
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ----------------- Reg Table Functions -----------------


def add_registration(
    email: str,
    first_name: str,
    last_name: str,
    is_capstone: bool,
    roles: list,
    *,
    is_professional: bool = False,
):
    """Adds a new user to the registration table."""
    get_category(is_capstone, is_professional)
    email = normalize_email(email)

    is_p = "participant" in roles
    is_j = "judge" in roles
    is_m = "mentor" in roles

    with _LOCK, _get_connection() as conn:
        # "Upsert" Logic: If email exists, UPDATE fields. If not, INSERT.
        conn.execute(
            f"""
            INSERT INTO {_REG_TABLE_NAME} (email, first_name, last_name, is_capstone, is_professional, is_participant, is_judge, is_mentor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                is_capstone = excluded.is_capstone,
                is_professional = excluded.is_professional,
                is_participant = excluded.is_participant,
                is_judge = excluded.is_judge,
                is_mentor = excluded.is_mentor
        """,
            (
                email,
                first_name,
                last_name,
                is_capstone,
                is_professional,
                is_p,
                is_j,
                is_m,
            ),
        )
        conn.commit()
    logger.debug("registration_upserted email=%r", email)


def remove_registration(email: str):
    """Deletes a user's registration and verification row"""
    with _LOCK, _get_connection() as conn:
        conn.execute(f"DELETE FROM {_REG_TABLE_NAME} WHERE email = ?", (email,))
        conn.commit()
    logger.debug("registration_removed email=%r", email)


def is_registered(email: str) -> bool:
    """Returns True if the email is found in the registration table."""

    with _get_connection() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {_REG_TABLE_NAME} WHERE email = ?", (email,)
        ).fetchone()
        return row is not None


def get_registration(email: str) -> dict:
    """Returns the user row as a dictionary, or None if they don't exist."""
    with _get_connection() as conn:
        row = conn.execute(
            f"SELECT * FROM {_REG_TABLE_NAME} WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None


def update_roles(email: str, roles: list):
    """Updates the role flags for a specific user."""

    is_p = "participant" in roles
    is_j = "judge" in roles
    is_m = "mentor" in roles

    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"""
            UPDATE {_REG_TABLE_NAME}
            SET is_participant = ?, is_judge = ?, is_mentor = ? 
            WHERE email = ?
        """,
            (is_p, is_j, is_m, email),
        )
        conn.commit()
    logger.debug("registration_roles_updated email=%r roles=%r", email, roles)


def get_all_registrants(role=None):
    """
    Returns a list of all registered users.
    Optional: Filter by role ('participant', 'judge', 'mentor').
    """
    query = f"SELECT * FROM {_REG_TABLE_NAME}"
    params = ()

    if role == "participant":
        query += " WHERE is_participant = 1"
    elif role == "judge":
        query += " WHERE is_judge = 1"
    elif role == "mentor":
        query += " WHERE is_mentor = 1"

    with _get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_first_name(email: str):
    return get_registration(email)["first_name"]


def get_user_roles(email: str) -> list:
    """
    Returns a list of role names based on the user's registration flags.
    Example return: ['participant', 'mentor']
    """
    with _get_connection() as conn:
        row = conn.execute(
            """
            SELECT is_participant, is_judge, is_mentor 
            FROM registration WHERE email = ?
        """,
            (email,),
        ).fetchone()

        if not row:
            return []

        roles = []
        if row["is_participant"]:
            roles.append("participant")
        if row["is_judge"]:
            roles.append("judge")
        if row["is_mentor"]:
            roles.append("mentor")

        return roles


# ------------- Verified Table Functions -----------------


def add_verified_user(
    email: str, discord_id: int, username: str, *, replace: bool = False
) -> bool:
    """Link a Discord user to a registration, optionally replacing its owner."""
    email = normalize_email(email)
    with _LOCK, _get_connection() as conn:
        if replace:
            conn.execute(
                f"DELETE FROM {_VERIFIED_TABLE_NAME} WHERE email = ?", (email,)
            )
        cursor = conn.execute(
            f"""
            INSERT INTO {_VERIFIED_TABLE_NAME} (email, discord_id, username)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (email, discord_id, username),
        )
        conn.commit()
    added = cursor.rowcount == 1
    if added:
        logger.debug("verified_user_added email=%r discord_id=%r", email, discord_id)
    else:
        logger.info("verified_user_already_exists email=%r", email)
    return added

def normalize_email(email: str) -> str:
    updatedEmail = email.lower().strip()
    updatedEmail = updatedEmail.replace(" ","")
    if updatedEmail.count("@") != 1:
        if "@" not in updatedEmail:
            logger.info("Missing '@' symbol: please reenter email")
            return ""
        else:
            logger.info("Email must only contain one '@' symbol: please reenter email")
            return ""
    return updatedEmail

def remove_verified_user(email: str):
    """Removes the verification status."""
    with _LOCK, _get_connection() as conn:
        conn.execute(f"DELETE FROM {_VERIFIED_TABLE_NAME} WHERE email = ?", (email,))
        conn.commit()
    logger.debug("verified_user_removed email=%r", email)


def is_verified(identifier) -> bool:
    """Checks verification status by Email (str) OR Discord ID (int)."""
    with _get_connection() as conn:
        if isinstance(identifier, int):  # Treat as Discord ID
            row = conn.execute(
                f"SELECT 1 FROM {_VERIFIED_TABLE_NAME} WHERE discord_id = ?",
                (identifier,),
            ).fetchone()
        elif isinstance(identifier, str):  # Treat as Email
            row = conn.execute(
                f"SELECT 1 FROM {_VERIFIED_TABLE_NAME} WHERE email = ?", (identifier,)
            ).fetchone()
        else:
            raise ValueError("Identifier must be an int (Discord ID) or str (Email)")
        return row is not None


def get_verified_user(identifier) -> dict:
    """Returns user data by accepting either a Discord ID (int) OR an Email (str)."""

    if isinstance(identifier, int):
        where_clause = "v.discord_id = ?"
    else:
        where_clause = "v.email = ?"

    with _get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT v.discord_id, v.username, v.team_id, 
                   r.email, r.first_name, r.last_name, 
                   r.is_participant, r.is_judge, r.is_mentor,
                   r.is_capstone, r.is_professional
            FROM {_VERIFIED_TABLE_NAME} v
            JOIN {_REG_TABLE_NAME} r ON v.email = r.email
            WHERE {where_clause}
        """,
            (identifier,),
        ).fetchone()

        return dict(row) if row else None


def get_verified_email(discord_id: int) -> str:
    """Finds the verified email associated with a Discord ID."""
    with _get_connection() as conn:
        row = conn.execute(
            f"SELECT email FROM {_VERIFIED_TABLE_NAME} WHERE discord_id = ?",
            (discord_id,),
        ).fetchone()
        return row["email"] if row else None


def join_team(discord_id: int, team_id: int) -> bool:
    """Assign an unassigned verified user to a team."""
    with _LOCK, _get_connection() as conn:
        cursor = conn.execute(
            f"""
            UPDATE {_VERIFIED_TABLE_NAME}
            SET team_id = ?
            WHERE discord_id = ? AND team_id IS NULL
            """,
            (team_id, discord_id),
        )
        conn.commit()
    claimed = cursor.rowcount == 1
    if claimed:
        logger.debug(
            "team_member_assigned discord_id=%r team_id=%r", discord_id, team_id
        )
    return claimed


def leave_team(discord_id: int, team_id: int | None = None) -> bool:
    """Remove a user from their current or expected team."""
    with _LOCK, _get_connection() as conn:
        if team_id is None:
            cursor = conn.execute(
                f"UPDATE {_VERIFIED_TABLE_NAME} SET team_id = NULL WHERE discord_id = ?",
                (discord_id,),
            )
        else:
            cursor = conn.execute(
                f"""
                UPDATE {_VERIFIED_TABLE_NAME}
                SET team_id = NULL
                WHERE discord_id = ? AND team_id = ?
                """,
                (discord_id, team_id),
            )
        conn.commit()
    removed = cursor.rowcount == 1
    if removed:
        logger.debug("team_member_unassigned discord_id=%r", discord_id)
    return removed


def get_user_team_id(identifier) -> int:
    """Returns the team_id (or None) by Email (str) OR Discord ID (int)."""
    with _get_connection() as conn:
        if isinstance(identifier, int):
            row = conn.execute(
                f"SELECT team_id FROM {_VERIFIED_TABLE_NAME} WHERE discord_id = ?",
                (identifier,),
            ).fetchone()
        elif isinstance(identifier, str):
            row = conn.execute(
                f"SELECT team_id FROM {_VERIFIED_TABLE_NAME} WHERE email = ?",
                (identifier,),
            ).fetchone()
        else:
            raise ValueError("Identifier must be an int (Discord ID) or str (Email)")
        return row["team_id"] if row else None


# ---------------- Team Table Functions ------------------


def create_team(
    name: str,
    is_capstone: bool,
    role_id: int,
    category_id: int,
    text_id: int,
    voice_id=None,
    *,
    is_professional: bool = False,
) -> int:
    """Creates a new team and returns its new database ID."""
    get_category(is_capstone, is_professional)
    with _LOCK, _get_connection() as conn:
        cursor = conn.execute(
            f"""
            INSERT INTO {_TEAM_TABLE_NAME} (name, is_capstone, is_professional, role_id, category_id, text_id, voice_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                name,
                is_capstone,
                is_professional,
                role_id,
                category_id,
                text_id,
                voice_id,
            ),
        )
        conn.commit()
        team_id = cursor.lastrowid
    logger.debug("team_created team_id=%r team_name=%r", team_id, name)
    return team_id


def remove_team(identifier):
    """
    Deletes a team by ID (int) or Name (str).
    Users on this team will have their team_id set to NULL (via ON DELETE SET NULL).
    """
    with _LOCK, _get_connection() as conn:
        if isinstance(identifier, int):
            conn.execute(f"DELETE FROM {_TEAM_TABLE_NAME} WHERE id = ?", (identifier,))
        elif isinstance(identifier, str):
            conn.execute(
                f"DELETE FROM {_TEAM_TABLE_NAME} WHERE name = ?", (identifier,)
            )
        else:
            raise ValueError("Identifier must be int (ID) or str (Name)")
        conn.commit()
    logger.debug("team_removed identifier=%r", identifier)


def team_exists(identifier) -> bool:
    """Checks if a team exists by ID (int) or Name (str)."""
    with _get_connection() as conn:
        if isinstance(identifier, int):
            row = conn.execute(
                f"SELECT 1 FROM {_TEAM_TABLE_NAME} WHERE id = ?", (identifier,)
            ).fetchone()
        elif isinstance(identifier, str):
            row = conn.execute(
                f"SELECT 1 FROM {_TEAM_TABLE_NAME} WHERE name = ?", (identifier,)
            ).fetchone()
        else:
            raise ValueError("Identifier must be int (ID) or str (Name)")
        return row is not None


def get_team(identifier) -> dict:
    """Retrieves team data (Channels, Category, Name) by ID (int) or Name (str)."""
    with _get_connection() as conn:
        if isinstance(identifier, int):
            row = conn.execute(
                f"SELECT * FROM {_TEAM_TABLE_NAME} WHERE id = ?", (identifier,)
            ).fetchone()
        elif isinstance(identifier, str):
            row = conn.execute(
                f"SELECT * FROM {_TEAM_TABLE_NAME} WHERE name = ?", (identifier,)
            ).fetchone()
        else:
            raise ValueError("Identifier must be int (ID) or str (Name)")

        return dict(row) if row else None


def get_team_size(identifier) -> int:
    """Returns the number of members currently on a specific team."""
    with _get_connection() as conn:
        if isinstance(identifier, int):
            # Query by ID directly
            count = conn.execute(
                f"SELECT COUNT(*) FROM {_VERIFIED_TABLE_NAME} WHERE team_id = ?",
                (identifier,),
            ).fetchone()[0]
        elif isinstance(identifier, str):
            # Query by Name: Look up team first, or use a subquery
            count = conn.execute(
                f"""
                SELECT COUNT(*) FROM {_VERIFIED_TABLE_NAME} 
                WHERE team_id = (SELECT id FROM {_TEAM_TABLE_NAME} WHERE name = ?)
            """,
                (identifier,),
            ).fetchone()[0]
        else:
            raise ValueError("Identifier must be int (ID) or str (Name)")
        return count


def get_max_team_id() -> int:
    """Returns the highest ID currently in the teams table."""
    with _get_connection() as conn:
        max_id = conn.execute(f"SELECT MAX(id) FROM {_TEAM_TABLE_NAME}").fetchone()[0]
        return max_id if max_id is not None else 0


def get_next_team_id() -> int:
    """Predicts the next ID that will be assigned to a team."""
    with _get_connection() as conn:
        cursor = conn.execute(
            f"SELECT seq FROM sqlite_sequence WHERE name = '{_TEAM_TABLE_NAME}'"
        )
        row = cursor.fetchone()
        if row:
            return row["seq"] + 1
        else:
            return 1


def get_all_teams() -> list:
    """Returns a list of all team dictionaries."""
    with _get_connection() as conn:
        rows = conn.execute(f"SELECT * FROM {_TEAM_TABLE_NAME}").fetchall()
        return [dict(row) for row in rows]


def set_team_lead(team_id: int, lead_id: int):
    """Assigns a specific user (Discord ID) as the Team Lead."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"UPDATE {_TEAM_TABLE_NAME} SET team_lead = ? WHERE id = ?",
            (lead_id, team_id),
        )
        conn.commit()
    logger.debug("team_lead_updated team_id=%r lead_id=%r", team_id, lead_id)


def remove_team_lead(team_id: int):
    """Removes the team lead assignment from a team (sets it to NULL)."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"UPDATE {_TEAM_TABLE_NAME} SET team_lead = NULL WHERE id = ?", (team_id,)
        )
        conn.commit()
    logger.debug("team_lead_removed team_id=%r", team_id)


def get_team_members(identifier) -> list:
    """
    Returns a list of dictionaries for all members on a team.
    Each dict contains: discord_id, username, email, first_name, last_name.

    Identifier can be Team ID (int) or Team Name (str).
    """
    query = f"""
        SELECT v.discord_id, v.username, v.email, r.first_name, r.last_name
        FROM {_VERIFIED_TABLE_NAME} v
        JOIN {_REG_TABLE_NAME} r ON v.email = r.email
    """

    with _get_connection() as conn:
        if isinstance(identifier, int):
            # Query by ID
            rows = conn.execute(
                f"{query} WHERE v.team_id = ?", (identifier,)
            ).fetchall()
        elif isinstance(identifier, str):
            # Query by Name (Subquery to find ID first)
            rows = conn.execute(
                f"""
                {query} 
                WHERE v.team_id = (SELECT id FROM teams WHERE name = ?)
            """,
                (identifier,),
            ).fetchall()
        else:
            raise ValueError("Identifier must be int (ID) or str (Name)")

        # Convert list of Row objects to list of dicts
        return [dict(row) for row in rows]


def set_grace_period(team_id: int, expires_at: float):
    """Set when an undersized team's grace period expires."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"UPDATE {_TEAM_TABLE_NAME} SET grace_period = ? WHERE id = ?",
            (expires_at, team_id),
        )
        conn.commit()


def clear_grace_period(team_id: int):
    """Clear a team's pending grace period."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"UPDATE {_TEAM_TABLE_NAME} SET grace_period = NULL WHERE id = ?",
            (team_id,),
        )
        conn.commit()


def get_all_grace_periods() -> list:
    """Return teams with active grace periods."""
    with _get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, grace_period
            FROM {_TEAM_TABLE_NAME}
            WHERE grace_period IS NOT NULL
            """
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------- Code Table Functions -----------------


def add_code(email: str, discord_id: int, code: str, expiration_time: int):
    """Stores a generated verification code and its expiration timestamp."""
    email = normalize_email(email)
    expires_at = time.time() + expiration_time
    with _LOCK, _get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO codes (code, discord_id, email, expires_at)
            VALUES (?, ?, ?, ?)
        """,
            (code, discord_id, email, expires_at),
        )
        conn.commit()
    logger.debug("verification_code_stored email=%r discord_id=%r", email, discord_id)


def code_exists(code: str) -> bool:
    """Checks if a verification code exists in the database."""
    with _get_connection() as conn:
        row = conn.execute("SELECT 1 FROM codes WHERE code = ?", (code,)).fetchone()
        return row is not None


def get_value_from_code(code: str) -> dict:
    """Retrieves the data linked to an unexpired code."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM codes WHERE code = ? AND expires_at > ?",
            (code, time.time()),
        ).fetchone()
        return dict(row) if row else None


def remove_code(code: str):
    """Deletes a code from the database."""
    with _LOCK, _get_connection() as conn:
        conn.execute("DELETE FROM codes WHERE code = ?", (code,))
        conn.commit()
    logger.debug("verification_code_deleted")


# -------------- Category Bucket Functions --------------


def get_latest_category() -> int:
    """Peek at the top of the stack. Returns Discord ID or None."""
    with _get_connection() as conn:
        # Order by ID descending to get the newest row
        row = conn.execute(
            f"SELECT discord_id FROM {_CATEGORY_BUCKET_NAME} ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["discord_id"] if row else None


def push_new_category(discord_id: int):
    """Push a new category onto the stack."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"INSERT INTO {_CATEGORY_BUCKET_NAME} (discord_id) VALUES (?)",
            (discord_id,),
        )
        conn.commit()
    logger.debug("category_stored category_id=%r", discord_id)


# ---------------- LFG (Looking For Group) Functions ----------------


def is_looking(discord_id: int) -> bool:
    """Returns True if the user is currently in the LFG pool."""
    with _get_connection() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {_LFG_TABLE_NAME} WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return row is not None


def add_to_lfg(discord_id: int, skills: str = None):
    """Adds a user to the LFG pool or updates their listed skills."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"""
            INSERT INTO {_LFG_TABLE_NAME} (discord_id, skills)
            VALUES (?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                skills = excluded.skills
        """,
            (discord_id, skills),
        )
        conn.commit()


def remove_from_lfg(discord_id: int):
    """Removes a user from the LFG pool; safe if absent."""
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"DELETE FROM {_LFG_TABLE_NAME} WHERE discord_id = ?", (discord_id,)
        )
        conn.commit()


def get_lfg_list(category: ParticipantCategory) -> list:
    """Returns unassigned LFG users in the requested participant category."""
    category = ParticipantCategory(category)
    is_capstone = category is ParticipantCategory.CAPSTONE
    is_professional = category is ParticipantCategory.PROFESSIONAL
    with _get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT l.discord_id, v.username, r.first_name, l.skills
            FROM {_LFG_TABLE_NAME} l
            JOIN {_VERIFIED_TABLE_NAME} v ON l.discord_id = v.discord_id
            JOIN {_REG_TABLE_NAME} r ON v.email = r.email
            WHERE v.team_id IS NULL
              AND r.is_capstone = ?
              AND r.is_professional = ?
            ORDER BY l.created_at ASC
        """,
            (is_capstone, is_professional),
        ).fetchall()
        return [dict(row) for row in rows]


_initialize_db()
