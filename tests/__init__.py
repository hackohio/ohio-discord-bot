"""Safe import configuration for the offline test suite."""

import os
import tempfile
from pathlib import Path

_TEST_RUNTIME = tempfile.TemporaryDirectory(prefix="ohio-discord-tests-")
_TEST_DATABASE = str(Path(_TEST_RUNTIME.name) / "import.db")
_TEST_CONFIG = Path(_TEST_RUNTIME.name) / "config.ini"
_TEST_CONFIG.write_text(
    """[discord]
 guild_id=1
 token=test-token
 start_here_channel_id=2
 ask_an_organizer_channel_id=3
 organizer_role_id=4
 participant_role_id=5
 mentor_role_id=6
 judge_role_id=7
 team_assigned_role_id=8
 all_access_pass_role_id=9
 verified_role_id=10
 shared_categories=false

[contact]
 registration_link=https://example.test/register
 organizer_email=organizer@example.test

[web]
 port=5000
 api_key=test-api-key-with-at-least-32-characters

[email]
 address=bot@example.test
 password=test-password
 code_expiration_time=600
""",
    encoding="utf-8",
)

# Set these before any application module is imported. The real defaults remain
# unchanged for production, while test imports cannot touch local event data.
os.environ["OHIO_RECORDS_DB"] = _TEST_DATABASE
os.environ["OHIO_CONFIG_FILE"] = str(_TEST_CONFIG)
