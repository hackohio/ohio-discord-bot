"""Team creation and membership commands."""

import logging
import random
import time
import uuid
from enum import IntEnum

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import records
from discord_bot.common import _log_rejection, audit_command, create_embed

logger = logging.getLogger(__name__)

MAX_TEAM_SIZE = 4
CAPSTONE_TEAM_SIZE = 5
TEAM_GRACE_PERIOD = 5 * 60


class TeamJoinStatus(IntEnum):
    ALLOWED = 0
    NOT_VERIFIED = -1
    NOT_PARTICIPANT = -2
    ALREADY_ON_TEAM = -3
    CAPSTONE_MISMATCH = -4


async def handle_team_deletion(team_id: int, guild: discord.Guild):  # TESTED
    """Unconditionally remove a team's roles, channels, and database row."""
    operation_id = uuid.uuid4().hex
    team_data = records.get_team(team_id)
    try:
        if records.team_exists(team_id):
            # Remove Role and team_id from each user on team
            for member in records.get_team_members(team_id):
                discord_member = (
                    guild.get_member(member["discord_id"]) if guild else None
                )
                if discord_member:
                    await perform_team_leave(discord_member, team_id, guild)

            # Remove all Channels
            await delete_team_channels(team_id, guild)
            records.remove_team(team_id)
        logger.info(
            "team_cleanup_completed operation_id=%r team_id=%r team_name=%r",
            operation_id,
            team_id,
            team_data.get("name") if team_data else None,
        )
    except Exception:
        logger.exception("team_cleanup_failed team_id=%r", team_id)
        raise


async def delete_team_channels(team_id: int, guild: discord.Guild):  # TESTED

    # Get all channels and role from database
    team_data = records.get_team(team_id)

    category_id = team_data["category_id"]
    text_id = team_data["text_id"]
    voice_id = team_data["voice_id"]
    role_id = team_data["role_id"]

    category = guild.get_channel(category_id) if category_id else None
    text = guild.get_channel(text_id) if text_id else None
    voice = guild.get_channel(voice_id) if voice_id else None
    role = guild.get_role(role_id) if role_id else None

    team_name = team_data.get("name") if team_data else None
    resources = (
        ("text_channel", text, text_id),
        ("voice_channel", voice, voice_id),
        ("role", role, role_id),
    )
    if category_id and not config.discord_shared_categories:
        resources += (("category", category, category_id),)
    for resource_type, resource, resource_id in resources:
        fields = {
            "team_id": team_id,
            "team_name": team_name,
            "guild_id": getattr(guild, "id", None),
            "resource_type": resource_type,
            "resource_id": resource_id,
        }
        if not resource:
            logger.warning(
                "discord_resource_missing details=%r outcome='skipped'", fields
            )
            continue
        try:
            await resource.delete()
        except Exception:
            logger.exception(
                "discord_resource_deletion_failed team_id=%r resource_type=%r resource_id=%r",
                team_id,
                resource_type,
                resource_id,
            )
            raise
        logger.info("discord_resource_deletion_completed details=%r", fields)


def can_join_team(
    added_member: discord.Member, capstone_team: bool | None = None
) -> TeamJoinStatus:  # TESTED
    """Return why a member can or cannot join a team."""

    if not records.is_verified(added_member.id):
        return TeamJoinStatus.NOT_VERIFIED

    email = records.get_verified_email(added_member.id)
    user_data = records.get_verified_user(email)
    if not user_data["is_participant"]:
        return TeamJoinStatus.NOT_PARTICIPANT

    if records.get_user_team_id(added_member.id):
        return TeamJoinStatus.ALREADY_ON_TEAM

    if capstone_team is not None and capstone_team != user_data["is_capstone"]:
        return TeamJoinStatus.CAPSTONE_MISMATCH
    return TeamJoinStatus.ALLOWED


async def perform_team_join(
    member: discord.Member, team_id: int, guild: discord.Guild
):  # TESTED
    team_data = records.get_team(team_id)
    # DB Update
    records.join_team(member.id, team_id)
    records.remove_from_lfg(member.id)

    team_data = records.get_team(team_id)

    # Get Roles to add
    roles_to_add = []
    if team_data and "role_id" in team_data:
        t_role = guild.get_role(team_data["role_id"])
        if t_role:
            roles_to_add.append(t_role)
    a_role = guild.get_role(config.discord_team_assigned_role_id)
    if a_role:
        roles_to_add.append(a_role)

    # Add Roles to Users
    if roles_to_add:
        role_fields = {
            "guild_id": getattr(guild, "id", None),
            "team_id": team_id,
            "role_ids": [role.id for role in roles_to_add],
            "target_id": member.id,
        }
        await member.add_roles(*roles_to_add)
        logger.info(
            "discord_role_mutation_completed operation='team_join' details=%r",
            role_fields,
        )
    logger.info(
        "team_member_join_completed team_id=%r team_name=%r target_id=%r",
        team_id,
        team_data.get("name") if team_data else None,
        member.id,
    )


async def perform_team_leave(
    member: discord.Member, team_id: int, guild: discord.Guild
):  # TESTED

    team_data = records.get_team(team_id)

    # Drop Team
    records.leave_team(member.id)

    # Get Roles to Remove
    roles_to_remove = []
    if team_data and "role_id" in team_data:
        t_role = guild.get_role(team_data["role_id"])
        if t_role:
            roles_to_remove.append(t_role)
    a_role = guild.get_role(config.discord_team_assigned_role_id)
    if a_role:
        roles_to_remove.append(a_role)

    # Remove Roles from User
    if roles_to_remove:
        role_fields = {
            "guild_id": getattr(guild, "id", None),
            "team_id": team_id,
            "role_ids": [role.id for role in roles_to_remove],
            "target_id": member.id,
        }
        await member.remove_roles(*roles_to_remove)
        logger.info(
            "discord_role_mutation_completed operation='team_leave' details=%r",
            role_fields,
        )
    logger.info(
        "team_member_leave_completed team_id=%r team_name=%r target_id=%r",
        team_id,
        team_data.get("name") if team_data else None,
        member.id,
    )


async def _notify_team_channel(team_id: int, guild: discord.Guild, content: str):
    team_data = records.get_team(team_id)
    channel = guild.get_channel(team_data["text_id"]) if team_data and guild else None
    if not channel:
        return
    try:
        await channel.send(content=content)
    except Exception:
        logger.exception("team_notification_failed team_id=%r", team_id)


async def _notify_remaining_member(team_id: int, guild: discord.Guild):
    members = records.get_team_members(team_id)
    if not members or not guild:
        return
    member = guild.get_member(members[0]["discord_id"])
    if not member:
        return
    try:
        await member.send(
            content=(
                "Your team has been deleted because it no longer has at least "
                "two members. You may create another team using `/create_team`."
            )
        )
    except Exception:
        logger.exception("team_deletion_dm_failed team_id=%r", team_id)


async def enforce_team_size_policy(
    team_id: int,
    guild: discord.Guild,
    *,
    departing_lead: bool = False,
    previous_size: int | None = None,
) -> bool:
    """Apply the minimum-size rules after a membership change.

    Returns whether the team was deleted.
    """
    team_data = records.get_team(team_id)
    if not team_data:
        return False

    size = records.get_team_size(team_id)
    if size == 0:
        await handle_team_deletion(team_id, guild)
        return True

    if size >= 2:
        if team_data.get("grace_period") is not None:
            records.clear_grace_period(team_id)
            await _notify_team_channel(
                team_id,
                guild,
                "Your team has at least two members again. Pending deletion has been cancelled.",
            )
        return False

    if departing_lead and previous_size == 2:
        await _notify_remaining_member(team_id, guild)
        await handle_team_deletion(team_id, guild)
        return True

    if team_data.get("grace_period") is None:
        deadline = time.time() + TEAM_GRACE_PERIOD
        records.set_grace_period(team_id, deadline)
        await _notify_team_channel(
            team_id,
            guild,
            (
                "Your team now has fewer than two members. Add another member "
                f"before <t:{int(deadline)}:F> or the team role and private "
                "channels will be deleted. You may create another team afterward."
            ),
        )
    return False


class TeamsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        if not self.cleanup_team_grace_periods.is_running():
            self.cleanup_team_grace_periods.start()

    def cog_unload(self):
        self.cleanup_team_grace_periods.cancel()

    @tasks.loop(seconds=30)
    async def cleanup_team_grace_periods(self):
        guild = self.bot.get_guild(config.discord_guild_id)
        if guild is None:
            logger.warning(
                "team_grace_period_cleanup_guild_unavailable guild_id=%r",
                config.discord_guild_id,
            )
            return

        now = time.time()
        for pending in records.get_all_grace_periods():
            if pending["grace_period"] > now:
                continue
            team_id = pending["id"]
            try:
                if not records.team_exists(team_id):
                    continue
                size = records.get_team_size(team_id)
                if size >= 2:
                    records.clear_grace_period(team_id)
                    await _notify_team_channel(
                        team_id,
                        guild,
                        "Your team has at least two members again. Pending deletion has been cancelled.",
                    )
                else:
                    if size == 1:
                        await _notify_remaining_member(team_id, guild)
                    await handle_team_deletion(team_id, guild)
            except Exception:
                logger.exception("team_grace_period_cleanup_failed team_id=%r", team_id)

    @cleanup_team_grace_periods.before_loop
    async def before_cleanup_team_grace_periods(self):
        await self.bot.wait_until_ready()

    @app_commands.guild_only()
    @app_commands.command(
        name="create_team", description="Create a new team for this event"
    )
    @app_commands.describe(team_name="Name/Label for your Team")
    @audit_command
    async def create_team(
        self,
        interaction: discord.Interaction,
        team_name: str,
        teammate_1: discord.Member,
        teammate_2: discord.Member = None,
        teammate_3: discord.Member = None,
    ):
        """
        Creates a new team, assigning user to team and creating necessary roles and channels

        Args:
            ctxt (discord.Interaction): The Context of the Interaction.
            flags (teamNameFlag): The flags passed containing the team name and teammates users.

        Requires:
            - cannot already be in team
            - user has to be verified and participant

            teamname: str = commands.flag(description = "Name of your team")
            teammate1: discord.Member = commands.flag(description="Username of Teammate")
            teammate2: discord.Member = None
            teammate3: discord.Member = None
        """

        # Retrieve Context
        user = interaction.user
        await interaction.response.defer(ephemeral=True)

        # ------------- Check if Team and Creator is Valid --------------------

        creator_errors = {
            TeamJoinStatus.NOT_VERIFIED: (
                "not_verified",
                "You are not verified! Please verify yourself with the /verify command",
            ),
            TeamJoinStatus.NOT_PARTICIPANT: (
                "not_participant",
                "You are not a participant. You cannot create a team",
            ),
            TeamJoinStatus.ALREADY_ON_TEAM: (
                "already_on_team",
                "You are already on a team. You can leave with the /leave_team command",
            ),
        }
        author_status = can_join_team(user)
        if author_status in creator_errors:
            reason, message = creator_errors[author_status]
            _log_rejection(interaction, reason)
            await interaction.edit_original_response(content=message)
            return

        if records.team_exists(team_name):
            _log_rejection(
                interaction,
                "team_name_in_use",
                team_name=team_name,
            )
            await interaction.edit_original_response(
                content="That team name is already in use. Please chose a different name",
            )
            return

        # Validate every explicitly selected teammate before creating anything.
        is_capstone = records.get_verified_user(user.id)["is_capstone"]
        members = [teammate_1, teammate_2, teammate_3]
        valid_members = []
        validation_errors = []
        selected_ids = set()
        for mem in members:
            if not mem:
                continue
            if mem.id == user.id:
                _log_rejection(
                    interaction,
                    "target_is_actor",
                    target_id=mem.id,
                    target_username=mem.name,
                )
                validation_errors.append("You cannot add yourself as a teammate.")
                continue
            if mem.id in selected_ids:
                validation_errors.append(f"{mem.mention} was selected more than once.")
                continue
            selected_ids.add(mem.id)
            status = can_join_team(mem, is_capstone)
            if status == TeamJoinStatus.ALLOWED:
                valid_members.append(mem)
            elif status in (
                TeamJoinStatus.NOT_VERIFIED,
                TeamJoinStatus.NOT_PARTICIPANT,
            ):
                validation_errors.append(
                    f"{mem.mention} is not a verified participant."
                )
            elif status == TeamJoinStatus.ALREADY_ON_TEAM:
                validation_errors.append(f"{mem.mention} is already on a team.")
            elif status == TeamJoinStatus.CAPSTONE_MISMATCH:
                validation_errors.append(
                    f"{mem.mention} does not have the same capstone status as you."
                )

        if not valid_members or validation_errors:
            if not validation_errors:
                validation_errors.append("Select at least one teammate.")
            _log_rejection(
                interaction,
                "invalid_teammates",
                team_name=team_name,
                invalid_count=len(validation_errors),
            )
            description = (
                "Fix these issues and try again:\n"
                + "\n".join(f"• {error}" for error in validation_errors)
                + "\n\nNo team was created."
            )
            await interaction.edit_original_response(
                embed=create_embed("Team creation failed", description)
            )
            return

        team_role = None
        category_channel = None
        text_channel = None
        voice_channel = None
        category_created = False
        team_id = None

        try:
            # -------------------- Create Team Channels -------------------------
            team_role = await interaction.guild.create_role(name=team_name)
            logger.info(
                "team_role_created interaction_id=%r guild_id=%r team_name=%r role_id=%r",
                interaction.id,
                interaction.guild.id,
                team_name,
                team_role.id,
            )

            category_channel_perms = {
                interaction.guild.get_role(
                    config.discord_all_access_pass_role_id
                ): discord.PermissionOverwrite(view_channel=True),
                interaction.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False
                ),
                team_role: discord.PermissionOverwrite(view_channel=True),
            }
            text_channel_perms = {
                interaction.guild.get_role(
                    config.discord_all_access_pass_role_id
                ): discord.PermissionOverwrite(view_channel=True),
                interaction.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False
                ),
                team_role: discord.PermissionOverwrite(view_channel=True),
            }
            voice_channel_perms = {
                team_role: discord.PermissionOverwrite(
                    connect=True, view_channel=True, speak=True
                ),
                interaction.guild.get_role(
                    config.discord_all_access_pass_role_id
                ): discord.PermissionOverwrite(
                    connect=True, view_channel=True, speak=True
                ),
                interaction.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False
                ),
            }

            next_team_id = records.get_next_team_id()
            if not config.discord_shared_categories:
                category_created = True
                category_channel = await interaction.guild.create_category_channel(
                    f"Team {next_team_id} - {team_name}",
                    overwrites=category_channel_perms,
                )
                logger.info(
                    "team_category_created interaction_id=%r guild_id=%r channel_id=%r team_name=%r",
                    interaction.id,
                    interaction.guild.id,
                    category_channel.id,
                    team_name,
                )
                text_channel = await category_channel.create_text_channel(
                    f"{team_name.replace(' ', '-')}-text", overwrites=text_channel_perms
                )
                logger.info(
                    "team_text_channel_created interaction_id=%r guild_id=%r channel_id=%r team_name=%r",
                    interaction.id,
                    interaction.guild.id,
                    text_channel.id,
                    team_name,
                )
                voice_channel = await category_channel.create_voice_channel(
                    f"{team_name.replace(' ', '-')}-voice",
                    overwrites=voice_channel_perms,
                )
                logger.info(
                    "team_voice_channel_created interaction_id=%r guild_id=%r channel_id=%r team_name=%r",
                    interaction.id,
                    interaction.guild.id,
                    voice_channel.id,
                    team_name,
                )
            else:
                channels_per_category = 50
                new_channel_needed = (
                    (next_team_id - 1) % channels_per_category == 0
                ) or not records.get_latest_category()
                if new_channel_needed:
                    category_created = True
                    category_channel = await interaction.guild.create_category_channel(
                        f"Teams {next_team_id} - {(next_team_id - 1) + channels_per_category}",
                        overwrites=category_channel_perms,
                    )
                    logger.info(
                        "team_category_created interaction_id=%r guild_id=%r channel_id=%r team_name=%r",
                        interaction.id,
                        interaction.guild.id,
                        category_channel.id,
                        team_name,
                    )
                else:
                    category_channel = interaction.guild.get_channel(
                        records.get_latest_category()
                    )
                text_channel = await category_channel.create_text_channel(
                    f"{next_team_id}-{team_name.replace(' ', '-')}-text",
                    overwrites=text_channel_perms,
                )
                logger.info(
                    "team_text_channel_created interaction_id=%r guild_id=%r channel_id=%r team_name=%r",
                    interaction.id,
                    interaction.guild.id,
                    text_channel.id,
                    team_name,
                )

            team_id = records.create_team(
                team_name,
                is_capstone,
                team_role.id,
                category_channel.id,
                text_channel.id,
                voice_channel.id if voice_channel else None,
            )
            logger.info(
                "team_database_row_created interaction_id=%r team_id=%r team_name=%r capstone=%r",
                interaction.id,
                team_id,
                team_name,
                is_capstone,
            )

            # Add the creator and all selected teammates only after all validation passed.
            await perform_team_join(user, team_id, interaction.guild)
            records.set_team_lead(team_id, user.id)
            for mem in valid_members:
                await perform_team_join(mem, team_id, interaction.guild)
            if config.discord_shared_categories and category_created:
                records.push_new_category(category_channel.id)
            logger.info(
                "team_creation_completed interaction_id=%r team_id=%r team_name=%r member_count=%r",
                interaction.id,
                team_id,
                team_name,
                len(valid_members) + 1,
            )
        except Exception:
            logger.exception(
                "team_creation_failed interaction_id=%r team_name=%r",
                interaction.id,
                team_name,
            )
            cleanup_done = False
            if team_id is not None:
                try:
                    await handle_team_deletion(team_id, interaction.guild)
                    cleanup_done = True
                except Exception:
                    logger.exception(
                        "team_creation_cleanup_failed interaction_id=%r team_id=%r",
                        interaction.id,
                        team_id,
                    )
            if not cleanup_done:
                for resource in (
                    voice_channel,
                    text_channel,
                    category_channel if category_created else None,
                    team_role,
                ):
                    if not resource:
                        continue
                    try:
                        await resource.delete()
                    except Exception:
                        logger.exception(
                            "team_creation_resource_cleanup_failed interaction_id=%r resource_id=%r",
                            interaction.id,
                            getattr(resource, "id", None),
                        )
                if team_id is not None:
                    try:
                        records.remove_team(team_id)
                    except Exception:
                        logger.exception(
                            "team_creation_database_cleanup_failed interaction_id=%r team_id=%r",
                            interaction.id,
                            team_id,
                        )
            await interaction.edit_original_response(
                content="Team creation failed while setting up Discord resources. No team was created. Please try again or contact an organizer."
            )
            return

        await interaction.edit_original_response(
            embed=create_embed(
                "Team created",
                f"Your team ({team_role.mention}) is ready.\nTeam channel: {text_channel.mention}",
            )
        )

        welcome_embed = create_embed(
            title=f"Welcome Team #{team_id}: {team_name}!",
            description=f"Manage your team using `/add_member`, `/remove_member`, `leave_team`, and `/my_team`.\n\n👑 **Team Lead:** {user.mention}",
        )
        if is_capstone:
            welcome_embed.description += "\n\u200b"
            welcome_embed.add_field(
                name="🎓 Capstone Team Rules",
                value=(
                    "- You can add up to **5 members** (All must be Capstone)\n"
                    "- You will be exclusively judged in the Capstone category\n"
                    f"[Re-register here if this is a mistake]({config.contact_registration_link})"
                ),
                inline=False,
            )
        try:
            await text_channel.send(embed=welcome_embed)
            for mem in valid_members:
                await text_channel.send(
                    embed=create_embed(
                        title="👋 New Teammate!",
                        description=f"{mem.mention} has been added to the team by {interaction.user.mention}",
                    )
                )
        except Exception:
            logger.exception(
                "team_notification_failed interaction_id=%r team_id=%r",
                interaction.id,
                team_id,
            )

    @app_commands.guild_only()
    @app_commands.command(name="leave_team", description="Leave your current team")
    @audit_command
    async def leave_team(self, interaction: discord.Interaction):  # TESTED
        """
        Command for a user to leave their current team.
        The user will:
            - be removed from the team
            - have team roles removed

        Team channel will be notified of departure. If not members are left, the team will be fully deleted.

        Args:
            ctxt (discord.Interaction): The Context of the Interaction.
        """

        user = interaction.user
        await interaction.response.defer(ephemeral=True)

        # ------------- Do Validation Checks --------------------

        # Ensure user is on a team
        if not records.get_user_team_id(user.id):
            _log_rejection(interaction, "not_on_team")
            await interaction.edit_original_response(
                content="You cannot leave a team since you are not assigned to one!",
            )
            return

        # ------------- Happy Case --------------------

        # Grab team information before removing the member.
        team_id = records.get_user_team_id(user.id)
        team_data = records.get_team(team_id)
        previous_size = records.get_team_size(team_id)
        departing_lead = team_data["team_lead"] == user.id
        team_text_channel = interaction.guild.get_channel(team_data["text_id"])
        team_role = interaction.guild.get_role(team_data["role_id"])

        await perform_team_leave(user, team_id, interaction.guild)
        deleted = await enforce_team_size_policy(
            team_id,
            interaction.guild,
            departing_lead=departing_lead,
            previous_size=previous_size,
        )
        role_mention = getattr(team_role, "mention", f"<@&{team_data['role_id']}>")
        await interaction.edit_original_response(
            content=(
                f"You have successfully left the team {role_mention}. "
                "The team was deleted because it no longer had enough members."
                if deleted
                else f"You have successfully been removed from the team {role_mention}"
            ),
        )
        if deleted:
            return

        # If they were team lead, replace team_lead.
        if departing_lead:
            new_lead_id = random.choice(records.get_team_members(team_id))["discord_id"]
            records.set_team_lead(team_id, new_lead_id)
            if team_text_channel:
                try:
                    await team_text_channel.send(
                        embed=create_embed(
                            "👋 Teammate Left!",
                            f"{user.mention} has left the team.\n{interaction.guild.get_member(new_lead_id).mention} has been randomly assigned as the new Team Lead.",
                        )
                    )
                except Exception:
                    logger.exception("team_notification_failed team_id=%r", team_id)
        elif team_text_channel:
            try:
                await team_text_channel.send(
                    embed=create_embed(
                        "👋 Teammate Left!", f"{user.mention} has left the team."
                    )
                )
            except Exception:
                logger.exception("team_notification_failed team_id=%r", team_id)

    @app_commands.guild_only()
    @app_commands.command(name="add_member", description="Add a member to your team")
    @app_commands.describe(member="The member to add to your team")
    @audit_command
    async def add_member(
        self, interaction: discord.Interaction, member: discord.Member
    ):  # TESTED
        """
        Adds a specified member to the team of the user who invokes the command.

        Args:
            ctxt (discord.Interaction): The Context of the Interaction.
            flags (userFlag): The user specified in the command input.
        """
        team_user = interaction.user  # User who invoked the command
        added_user = member  # The user to be added to the taem
        await interaction.response.defer(ephemeral=True)

        # ------------- Do Validation Checks --------------------

        # Check that team_user is in a team
        if not records.get_user_team_id(team_user.id):
            _log_rejection(interaction, "not_on_team", target=member)
            await interaction.edit_original_response(
                content="Failed to add team member. You are not currently in a team. You must be in a team to add a team member. Please use `/create_team` to create a team or have another participant use `/add_member` to add you to their team",
            )
            return

        # Check if member is already on your team
        if records.get_user_team_id(team_user.id) == records.get_user_team_id(
            member.id
        ):
            _log_rejection(interaction, "already_on_team", target=member)
            await interaction.edit_original_response(
                content=f"Failed to add team member. {member.mention} is already on your team!",
            )
            return

        # Check that team is not full
        team_id = records.get_user_team_id(team_user.id)
        is_capstone = records.get_team(team_id)["is_capstone"]
        max_team_size = CAPSTONE_TEAM_SIZE if is_capstone else MAX_TEAM_SIZE
        if records.get_team_size(team_id) >= max_team_size:
            _log_rejection(
                interaction,
                "team_full",
                team_id=team_id,
                size=records.get_team_size(team_id),
                max_size=max_team_size,
                target=member,
            )
            await interaction.edit_original_response(
                content=f"Failed to add team member. There is no space in your team. Teams can have a maximum of {max_team_size} members.",
            )
            return

        # Check if user can join the team
        status = can_join_team(added_user, is_capstone)
        if status in (
            TeamJoinStatus.NOT_VERIFIED,
            TeamJoinStatus.NOT_PARTICIPANT,
        ):
            _log_rejection(
                interaction,
                "not_participant",
                team_id=team_id,
                target=added_user,
            )
            await interaction.edit_original_response(
                content=f"Failed to add team member. {added_user.mention} is not a verified participant.",
            )
            return
        if status == TeamJoinStatus.ALREADY_ON_TEAM:
            _log_rejection(
                interaction,
                "already_on_team",
                team_id=team_id,
                target=added_user,
            )
            await interaction.edit_original_response(
                content=f"Failed to add team member. {added_user.mention} is already on a team. To join, they must leave using /leave_team",
            )
            return
        if status == TeamJoinStatus.CAPSTONE_MISMATCH:
            _log_rejection(
                interaction,
                "capstone_mismatch",
                team_id=team_id,
                target=added_user,
            )
            await interaction.edit_original_response(
                content=f"Failed to add team member. {added_user.mention} is {'NOT ' if is_capstone else ''}registered as a capstone participant while you are {'' if is_capstone else 'NOT '}registered as capstone. If this is a mistake, members can re-regsiter at {config.contact_registration_link}",
            )
            return

        # ------------- Happy Case --------------------

        # Add the member to the team and cancel a pending deletion if applicable.
        await perform_team_join(added_user, team_id, interaction.guild)
        await enforce_team_size_policy(team_id, interaction.guild)

        team_data = records.get_team(team_id)
        text_channel = interaction.guild.get_channel(team_data["text_id"])

        # Send confirmation message to team_user
        await interaction.edit_original_response(
            content=f"{added_user.mention} has been added successfully"
        )

        # Notify team in team text channel of new member
        await text_channel.send(
            embed=create_embed(
                title="👋 New Teammate!",
                description=f"{added_user.mention} has been added to the team by {interaction.user.mention}",
            )
        )

    @app_commands.guild_only()
    @app_commands.command(
        name="remove_member",
        description="Remove a member from your team (Team Lead Only)",
    )
    @app_commands.describe(member="The member to remove from your team")
    @audit_command
    async def remove_member(
        self, interaction: discord.Interaction, member: discord.Member
    ):  # TESTED
        """
        Removes a specific member from the team of the user who invokes the command.
        User must be a "team_lead" to invoke (Created the team)
        Args:
            ctxt (discord.Interaction): The Context of the Interaction.
            member (discord.Member): The user to be removed.
        """
        team_user = interaction.user  # User who invoked the command

        await interaction.response.defer(ephemeral=True)

        # ------------- Do Validation Checks --------------------

        # Check that team_user is in a team
        if not records.get_user_team_id(team_user.id):
            _log_rejection(interaction, "not_on_team", target=member)
            await interaction.edit_original_response(
                content="Failed to remove team member. You are not currently in a team."
            )
            return

        # Check that user is the team_lead
        team_id = records.get_user_team_id(team_user.id)
        team_lead_id = records.get_team(team_id)["team_lead"]
        if team_lead_id != team_user.id:
            _log_rejection(
                interaction,
                "not_team_lead",
                team_id=team_id,
                expected_lead_id=team_lead_id,
                target=member,
            )
            await interaction.edit_original_response(
                content=f"Only the Team Lead can invoke this command!\n{interaction.guild.get_member(team_lead_id).mention} is your lead. Contact them to invoke the command"
            )
            return

        # Team lead cannot remove themselves
        if member.id == team_user.id:
            _log_rejection(interaction, "target_is_actor", team_id=team_id)
            await interaction.edit_original_response(
                content="You cannot remove yourself from the team. To leave the team, please use the `/leave_team` command."
            )
            return

        # Check if member is on your team
        if records.get_user_team_id(team_user.id) != records.get_user_team_id(
            member.id
        ):
            _log_rejection(
                interaction,
                "member_not_on_team",
                team_id=team_id,
                target=member,
            )
            await interaction.edit_original_response(
                content=f"Failed to remove team member. {member.mention} is not on your team!"
            )
            return

        # ------------- Happy Case --------------------

        previous_size = records.get_team_size(team_id)
        await perform_team_leave(member, team_id, interaction.guild)
        await enforce_team_size_policy(
            team_id,
            interaction.guild,
            previous_size=previous_size,
        )

        team_data = records.get_team(team_id)
        text_channel = interaction.guild.get_channel(team_data["text_id"])

        await interaction.edit_original_response(
            content=f"{member.mention} has been removed successfully."
        )

        if text_channel:
            try:
                await text_channel.send(
                    embed=create_embed(
                        title="👋 Teammate Removed!",
                        description=f"{member.mention} has been removed from the team by {team_user.mention}",
                    )
                )
            except Exception:
                logger.exception("team_notification_failed team_id=%r", team_id)

        try:
            await member.send(
                content=f"You have been removed from the team <{team_data['name']}>. \nYou can join a new team or create your own using `/create_team`"
            )
        except Exception:
            logger.exception("team_removal_dm_failed team_id=%r", team_id)

    @app_commands.guild_only()
    @app_commands.command(
        name="my_team", description="Get information about your current team"
    )
    @audit_command
    async def my_team(self, interaction: discord.Interaction):
        """
        Provides information about the user's current team, including team name, members, and team lead.

        Args:
            interaction (discord.Interaction): The Context of the Interaction.
        """

        user = interaction.user
        guild = interaction.guild
        if not guild:
            _log_rejection(interaction, "guild_unavailable")
            await interaction.response.send_message(
                content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)

        # Check if user is on a team
        team_id = records.get_user_team_id(user.id)
        if not team_id:
            _log_rejection(interaction, "not_on_team")
            await interaction.edit_original_response(
                content="You are not currently assigned to a team."
            )
            return

        # Retrieve team information
        team_data = records.get_team(team_id)
        if not team_data:
            _log_rejection(interaction, "team_not_found", team_id=team_id)
            await interaction.edit_original_response(
                content="There was an error retrieving your team information. Please contact an organizer for assistance."
            )
            return
        team_name = team_data["name"]
        team_lead_id = team_data["team_lead"]
        team_lead_member = guild.get_member(team_lead_id)
        if not team_lead_member:
            _log_rejection(
                interaction,
                "team_lead_not_in_guild",
                team_id=team_id,
                lead_id=team_lead_id,
            )
            await interaction.edit_original_response(
                content="There was an error retrieving your team information. Please contact an organizer for assistance."
            )
            return

        team_members = records.get_team_members(team_id)

        # Format member list
        mentions = []
        for member in team_members:
            discord_member = guild.get_member(member["discord_id"])
            if discord_member:
                mentions.append(f"- {discord_member.mention}")
        member_list = "\n".join(mentions)

        # Create and send embed with team information
        embed = create_embed(
            title=f"Your Team: {team_name}",
            description=f"**Team Lead:** {team_lead_member.mention}\n\n**Members:**\n{member_list}",
        )
        await interaction.edit_original_response(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamsCog(bot))
