import configparser
import logging

logger = logging.getLogger(__name__)

# Init Vars
config_data = configparser.ConfigParser()
CONFIG_FILENAME = "config.ini"

# Required configuration entries in _CONFIG_FILENAME, a list of tuples of
# (section: str, option: str)
_REQUIRED_CONFIG_ENTRIES = [
    ("discord", "guild_id"),
    ("discord", "token"),
    ("discord", "start_here_channel_id"),
    ("discord", "ask_an_organizer_channel_id"),
    ("discord", "organizer_role_id"),
    ("discord", "participant_role_id"),
    ("discord", "mentor_role_id"),
    ("discord", "judge_role_id"),
    ("discord", "team_assigned_role_id"),
    ("discord", "all_access_pass_role_id"),
    ("discord", "verified_role_id"),
    ("discord", "shared_categories"),
    ("contact", "registration_link"),
    ("contact", "organizer_email"),
    ("web", "port"),
    ("web", "api_key"),
    ("email", "address"),
    ("email", "password"),
    ("email", "code_expiration_time"),
]

# Import Data from CONFIG_FILENAME into _config
try:
    config_data.read(CONFIG_FILENAME)
except configparser.Error as exc:
    logger.error(
        "configuration_read_failed filename=%r exception=%r",
        CONFIG_FILENAME,
        type(exc).__name__,
    )
    raise SystemExit(1) from None


# Check that all required entries are present
for entry in _REQUIRED_CONFIG_ENTRIES:
    try:
        config_data.get(entry[0], entry[1])
    except (configparser.Error, TypeError) as exc:
        logger.error(
            "configuration_missing filename=%r section=%r option=%r exception=%r",
            CONFIG_FILENAME,
            entry[0],
            entry[1],
            type(exc).__name__,
        )
        raise SystemExit(1) from None


def strtobool(str: str) -> bool:
    if str == "true":
        return True
    elif str == "false":
        return False
    raise ValueError('Value must be "true" or "false"')


def _get_int(section: str, option: str) -> int:
    try:
        return int(config_data[section][option])
    except (TypeError, ValueError) as exc:
        logger.error(
            "configuration_invalid filename=%r section=%r option=%r exception=%r",
            CONFIG_FILENAME,
            section,
            option,
            type(exc).__name__,
        )
        raise SystemExit(1) from None


def _get_bool(section: str, option: str) -> bool:
    try:
        return strtobool(config_data[section][option])
    except ValueError as exc:
        logger.error(
            "configuration_invalid filename=%r section=%r option=%r exception=%r",
            CONFIG_FILENAME,
            section,
            option,
            type(exc).__name__,
        )
        raise SystemExit(1) from None


# Declare relevant variables to be retrieved
discord_guild_id = _get_int("discord", "guild_id")
discord_token = config_data["discord"]["token"]
discord_start_here_channel_id = _get_int("discord", "start_here_channel_id")
discord_ask_an_organizer_channel_id = _get_int("discord", "ask_an_organizer_channel_id")
discord_organizer_role_id = _get_int("discord", "organizer_role_id")
discord_participant_role_id = _get_int("discord", "participant_role_id")
discord_mentor_role_id = _get_int("discord", "mentor_role_id")
discord_judge_role_id = _get_int("discord", "judge_role_id")
discord_team_assigned_role_id = _get_int("discord", "team_assigned_role_id")
discord_all_access_pass_role_id = _get_int("discord", "all_access_pass_role_id")
discord_verified_role_id = _get_int("discord", "verified_role_id")
discord_shared_categories = _get_bool("discord", "shared_categories")
contact_registration_link = config_data["contact"]["registration_link"]
contact_organizer_email = config_data["contact"]["organizer_email"]
web_port = _get_int("web", "port")
web_api_key = config_data["web"]["api_key"]
email_address = config_data["email"]["address"]
email_password = config_data["email"]["password"]
email_code_expiration_time = _get_int("email", "code_expiration_time")

logger.info("configuration_loaded filename=%r web_port=%r", CONFIG_FILENAME, web_port)
