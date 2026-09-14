"""Team creation and membership commands."""

import logging
import random
import uuid

import discord
from discord import app_commands
from discord.ext import commands

import config
import records
from discord_bot.common import _log_rejection, audit_command, create_embed

logger = logging.getLogger(__name__)

MAX_TEAM_SIZE = 4
CAPSTONE_TEAM_SIZE = 5
TEAM_FORMATION_TIMEOUT = 120

async def handle_team_deletion(team_id: int, guild: discord.Guild):  # TESTED
    """
    Handles the timeout of team formation when team doesn't meet minimum size requirement

    If team has fewer than two members when timeout, this function will:
        1. remove team assigned role from all current members of team.
        2. remove team association from members in database
        3. delete team associated channels
        4. sends message explaining timeout and team re-creation process

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        team_id (int): The unique ID of the team
    """
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
    added_member: discord.Member, capstone_team: bool = None
) -> int:  # TESTED
    """Checks if User can join a team whether capstone, not capstone, or unspecified"""

    # Check that added_user is verified
    if not records.is_verified(added_member.id):
        return -1

    # Check if added_user is a participant
    email = records.get_verified_email(added_member.id)
    user_data = records.get_verified_user(email)
    if not user_data["is_participant"]:
        return -2

    # Check if add_user is already on a team
    if records.get_user_team_id(added_member.id):
        return -3

    # Check if user can join if a capstone team if relavent (not None)
    if capstone_team is not None and capstone_team != user_data["is_capstone"]:
        return -4
    return 0


async def perform_team_join(member: discord.Member, team_id: int, guild: discord.Guild):  # TESTED
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


async def perform_team_leave(member: discord.Member, team_id: int, guild: discord.Guild):  # TESTED

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


class TeamsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command(name="create_team", description="Create a new team for this event")
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
        operation_id = uuid.uuid4().hex

        # ------------- Check if Team and Creator is Valid --------------------

        author_status = can_join_team(user)
        match author_status:
            case -1:
                _log_rejection(interaction, "not_verified", operation_id=operation_id)
                await interaction.followup.send(
                    content="You are not verified! Please verify yourself with the /verify command",
                )
                return
            case -2:
                _log_rejection(interaction, "not_participant", operation_id=operation_id)
                await interaction.followup.send(
                    content="You are not a participant. You cannot create a team",
                )
                return
            case -3:
                _log_rejection(interaction, "already_on_team", operation_id=operation_id)
                await interaction.followup.send(
                    content="You are already on a team. You can leave with the /leave_team command",
                )
                return

        # Check that team doesn't already exist
        if records.team_exists(team_name):
            _log_rejection(
                interaction,
                "team_name_in_use",
                operation_id=operation_id,
                team_name=team_name,
            )
            await interaction.followup.send(
                content="That team name is already in use. Please chose a different name",
            )
            return

        # -------------- Check if Members added are Valid -------------------

        is_capstone = records.get_verified_user(user.id)["is_capstone"]

        # Check that atleast one member can be added to team
        members = [teammate_1, teammate_2, teammate_3]
        valid_members = []
        for mem in members:
            if not mem:
                continue
            if mem.id == user.id:
                _log_rejection(
                    interaction,
                    "target_is_actor",
                    operation_id=operation_id,
                    target_id=mem.id,
                    target_username=mem.name,
                )
                await interaction.followup.send(
                    ephemeral=True,
                    content="Failed to add team member. You cannot add yourself as a teammate.",
                )
                continue
            match can_join_team(mem, is_capstone):
                case -1 | -2:
                    await interaction.followup.send(
                        ephemeral=True,
                        content=f"Failed to add team member. {mem.mention} is not a verified participant.",
                    )
                case -3:
                    await interaction.followup.send(
                        ephemeral=True,
                        content=f"Failed to add team member. {mem.mention} is already on a team. To join, they must leave using /leaveteam",
                    )
                case -4:
                    await interaction.followup.send(
                        ephemeral=True,
                        content=f"Failed to add team member. {mem.mention} is {'NOT ' if is_capstone else ''}registered as a capstone participant while you are {'' if is_capstone else 'NOT '}registered as capstone. If this is a mistake, members can re-regsiter at {config.contact_registration_link}",
                    )
                case 0:
                    valid_members.append(mem)

        if not valid_members:
            _log_rejection(
                interaction,
                "no_valid_teammates",
                operation_id=operation_id,
                team_name=team_name,
            )
            await interaction.followup.send(
                ephemeral=True,
                content="Team creation failed - No teammates could be added. \nChoose a different teammate or reach out to them to fix their problem.",
            )
            return

        # -------------------- Create Team Channels -------------------------

        team_role = await interaction.guild.create_role(name=team_name)
        logger.info(
            "team_role_created operation_id=%r guild_id=%r team_name=%r role_id=%r",
            operation_id,
            interaction.guild.id,
            team_name,
            team_role.id,
        )

        category_channel_perms = {
            interaction.guild.get_role(
                config.discord_all_access_pass_role_id
            ): discord.PermissionOverwrite(view_channel=True),
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            team_role: discord.PermissionOverwrite(view_channel=True),
        }
        text_channel_perms = {
            interaction.guild.get_role(
                config.discord_all_access_pass_role_id
            ): discord.PermissionOverwrite(view_channel=True),
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            team_role: discord.PermissionOverwrite(view_channel=True),
        }
        voice_channel_perms = {
            team_role: discord.PermissionOverwrite(
                connect=True, view_channel=True, speak=True
            ),
            interaction.guild.get_role(
                config.discord_all_access_pass_role_id
            ): discord.PermissionOverwrite(connect=True, view_channel=True, speak=True),
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }

        next_team_id = records.get_next_team_id()
        category_channel = None
        text_channel = None
        voice_channel = None

        # Case 1: Each team has their own category and voice channel
        if not config.discord_shared_categories:
            category_channel = await interaction.guild.create_category_channel(
                f"Team {next_team_id} - {team_name}", overwrites=category_channel_perms
            )
            logger.info(
                "team_category_created operation_id=%r guild_id=%r channel_id=%r team_name=%r",
                operation_id,
                interaction.guild.id,
                category_channel.id,
                team_name,
            )
            text_channel = await category_channel.create_text_channel(
                f"{team_name.replace(' ', '-')}-text", overwrites=text_channel_perms
            )
            logger.info(
                "team_text_channel_created operation_id=%r guild_id=%r channel_id=%r team_name=%r",
                operation_id,
                interaction.guild.id,
                text_channel.id,
                team_name,
            )
            voice_channel = await category_channel.create_voice_channel(
                f"{team_name.replace(' ', '-')}-voice", overwrites=voice_channel_perms
            )
            logger.info(
                "team_voice_channel_created operation_id=%r guild_id=%r channel_id=%r team_name=%r",
                operation_id,
                interaction.guild.id,
                voice_channel.id,
                team_name,
            )

        # Case 2: Categories hold text-channels 1-50, etc
        else:
            channels_per_category = 50
            new_channel_needed = (
                (next_team_id - 1) % channels_per_category == 0
            ) or not records.get_latest_category()

            if new_channel_needed:  # New category channel needs made
                category_channel = await interaction.guild.create_category_channel(
                    f"Teams {next_team_id} - {(next_team_id - 1) + channels_per_category}",
                    overwrites=category_channel_perms,
                )
                records.push_new_category(category_channel.id)
                logger.info(
                    "team_category_created operation_id=%r guild_id=%r channel_id=%r team_name=%r",
                    operation_id,
                    interaction.guild.id,
                    category_channel.id,
                    team_name,
                )
            else:  # Use a previous team's category channel
                category_channel = interaction.guild.get_channel(records.get_latest_category())
            text_channel = await category_channel.create_text_channel(
                f"{next_team_id}-{team_name.replace(' ', '-')}-text",
                overwrites=text_channel_perms,
            )  # Inherit perms from Category
            logger.info(
                "team_text_channel_created operation_id=%r guild_id=%r channel_id=%r team_name=%r",
                operation_id,
                interaction.guild.id,
                text_channel.id,
                team_name,
            )

        # ----------------------- Create Team ------------------------

        team_id = records.create_team(
            team_name,
            is_capstone,
            team_role.id,
            category_channel.id,
            text_channel.id,
            voice_channel.id if voice_channel else None,
        )
        logger.info(
            "team_database_row_created operation_id=%r team_id=%r team_name=%r capstone=%r",
            operation_id,
            team_id,
            team_name,
            is_capstone,
        )

        # Respond to creator and send message to team channel
        await interaction.followup.send(
            content=f"Your Team ({team_role.mention}) has successfully been created!\n Your Team Channel: {text_channel.mention}",
            ephemeral=True,
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
        await text_channel.send(embed=welcome_embed)

        # Add Author and Valid Teammates to team
        await perform_team_join(user, team_id, interaction.guild)  # Add author to team
        records.set_team_lead(team_id, user.id)  # Make author team_lead
        for mem in valid_members:
            await perform_team_join(mem, team_id, interaction.guild)
            await text_channel.send(
                embed=create_embed(
                    title="👋 New Teammate!",
                    description=f"{mem.mention} has been added to the team by {interaction.user.mention}",
                )
            )
        logger.info(
            "team_creation_completed operation_id=%r team_id=%r team_name=%r member_count=%r",
            operation_id,
            team_id,
            team_name,
            len(valid_members) + 1,
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
            await interaction.followup.send(
                content="You cannot leave a team since you are not assigned to one!",
            )
            return

        # ------------- Happy Case --------------------

        # Grab Team Relavent Info
        team_id = records.get_user_team_id(user.id)
        team_data = records.get_team(team_id)
        team_text_channel = interaction.guild.get_channel(team_data["text_id"])
        team_role = interaction.guild.get_role(team_data["role_id"])

        # Remove user from team
        await perform_team_leave(user, team_id, interaction.guild)
        await interaction.followup.send(
            content=f"You have successfully been removed from the team {team_role.mention}",
        )

        # Delete team if no one is left
        if records.get_team_size(team_id) == 0:
            await handle_team_deletion(team_id, interaction.guild)
            return

        # If they were team lead, replace team_lead
        team_lead_id = team_data["team_lead"]
        if team_lead_id == user.id:
            # Chose a random other teammate to assign as lead
            new_lead_id = random.choice(records.get_team_members(team_id))["discord_id"]
            records.set_team_lead(team_id, new_lead_id)
            await team_text_channel.send(
                embed=create_embed(
                    "👋 Teammate Left!",
                    f"{user.mention} has left the team.\n{interaction.guild.get_member(new_lead_id).mention} has been randomly assigned as the new Team Lead.",
                )
            )

        else:
            await team_text_channel.send(
                embed=create_embed(
                    "👋 Teammate Left!", f"{user.mention} has left the team."
                )
            )

    @app_commands.guild_only()
    @app_commands.command(name="add_member", description="Add a member to your team")
    @app_commands.describe(member="The member to add to your team")
    @audit_command
    async def add_member(
        self,
        interaction: discord.Interaction, member: discord.Member
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
            await interaction.followup.send(
                content="Failed to add team member. You are not currently in a team. You must be in a team to add a team member. Please use `/create_team` to create a team or have another participant use `/add_member` to add you to their team",
            )
            return

        # Check if member is already on your team
        if records.get_user_team_id(team_user.id) == records.get_user_team_id(member.id):
            _log_rejection(interaction, "already_on_team", target=member)
            await interaction.followup.send(
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
            await interaction.followup.send(
                content=f"Failed to add team member. There is no space in your team. Teams can have a maximum of {max_team_size} members.",
            )
            return

        # Check if user can join the team
        match can_join_team(added_user, is_capstone):
            case -1 | -2:
                _log_rejection(
                    interaction,
                    "not_participant",
                    team_id=team_id,
                    target=added_user,
                )
                await interaction.followup.send(
                    content=f"Failed to add team member. {added_user.mention} is not a verified participant.",
                )
                return
            case -3:
                _log_rejection(
                    interaction,
                    "already_on_team",
                    team_id=team_id,
                    target=added_user,
                )
                await interaction.followup.send(
                    content=f"Failed to add team member. {added_user.mention} is already on a team. To join, they must leave using /leave_team",
                )
                return
            case -4:
                _log_rejection(
                    interaction,
                    "capstone_mismatch",
                    team_id=team_id,
                    target=added_user,
                )
                await interaction.followup.send(
                    content=f"Failed to add team member. {added_user.mention} is {'NOT ' if is_capstone else ''}registered as a capstone participant while you are {'' if is_capstone else 'NOT '}registered as capstone. If this is a mistake, members can re-regsiter at {config.contact_registration_link}",
                )
                return

        # ------------- Happy Case --------------------

        # Add the member to the team
        await perform_team_join(added_user, team_id, interaction.guild)

        team_data = records.get_team(team_id)
        text_channel = interaction.guild.get_channel(team_data["text_id"])

        # Send confirmation message to team_user
        await interaction.followup.send(
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
        name="remove_member", description="Remove a member from your team (Team Lead Only)"
    )
    @app_commands.describe(member="The member to remove from your team")
    @audit_command
    async def remove_member(
        self,
        interaction: discord.Interaction, member: discord.Member
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
            await interaction.followup.send(
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
            await interaction.followup.send(
                content=f"Only the Team Lead can invoke this command!\n{interaction.guild.get_member(team_lead_id).mention} is your lead. Contact them to invoke the command"
            )
            return

        # Team lead cannot remove themselves
        if member.id == team_user.id:
            _log_rejection(interaction, "target_is_actor", team_id=team_id)
            await interaction.followup.send(
                content="You cannot remove yourself from the team. To leave the team, please use the `/leave_team` command."
            )
            return

        # Check if member is on your team
        if records.get_user_team_id(team_user.id) != records.get_user_team_id(member.id):
            _log_rejection(
                interaction,
                "member_not_on_team",
                team_id=team_id,
                target=member,
            )
            await interaction.followup.send(
                content=f"Failed to remove team member. {member.mention} is not on your team!"
            )
            return

        # ------------- Happy Case --------------------

        # Remove member from team
        await perform_team_leave(member, team_id, interaction.guild)

        team_data = records.get_team(team_id)
        text_channel = interaction.guild.get_channel(team_data["text_id"])

        # Send confirmation message to team_user
        await interaction.followup.send(
            content=f"{member.mention} has been removed successfully."
        )

        # Notify team in team text channel of new member
        await text_channel.send(
            embed=create_embed(
                title="👋 Teammate Removed!",
                description=f"{member.mention} has been removed from the team by {team_user.mention}",
            )
        )

        # Notify removed member over dm
        await member.send(
            content=f"You have been removed from the team <{team_data['name']}>. \nYou can join a new team or create your own using `/create_team`"
        )

    @app_commands.guild_only()
    @app_commands.command(name="my_team", description="Get information about your current team")
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
            await interaction.followup.send(
                content="You are not currently assigned to a team."
            )
            return

        # Retrieve team information
        team_data = records.get_team(team_id)
        if not team_data:
            _log_rejection(interaction, "team_not_found", team_id=team_id)
            await interaction.followup.send(
                content="There was an error retrieving your team information. Please contact an organizer for assistance."
            )
            return
        team_name = team_data["name"]
        team_lead_id = team_data["team_lead"]
        team_lead_member = guild.get_member(team_lead_id)
        if not team_lead_member:
            _log_rejection(
                interaction, "team_lead_not_in_guild", team_id=team_id, lead_id=team_lead_id
            )
            await interaction.followup.send(
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
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamsCog(bot))

