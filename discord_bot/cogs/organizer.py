"""Organizer-only commands."""

import logging
from typing import Union, cast

import discord
from discord import app_commands
from discord.ext import commands

import config
import records
from discord_bot.cogs.teams import handle_team_deletion
from discord_bot.cogs.verification import sync_user_roles
from discord_bot.common import _log_rejection, audit_command, create_embed

logger = logging.getLogger(__name__)


class OrganizerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(
        name="overify",
        description="Manually verify a Discord account for this event (Organizers only)",
    )
    @app_commands.describe(
        role="User role: mentor, judge, participant, or mentor/judge"
    )
    @app_commands.choices(
        role=[
            app_commands.Choice(name="mentor", value="mentor"),
            app_commands.Choice(name="judge", value="judge"),
            app_commands.Choice(name="participant", value="participant"),
            app_commands.Choice(name="mentor/judge", value="mentor/judge"),
        ]
    )
    @audit_command
    async def overify(
        self,
        interaction: discord.Interaction,
        member_to_promote: discord.Member,
        email_address: str,
        first_name: str,
        last_name: str,
        is_capstone: bool,
        role: str,
    ):  # TESTED
        """
        Manually verifies a Discord account for the event, allowing organizers to assign roles and verify users.

        If the user doesn't exist, add them to the database and assign roles.
        If the user exists, update role and updata database.
        Args:
            ctxt (discord.Interaction): The Context of the Interaction.
            flags (registerFlag): Flag that contains registrant information (user, email, and role)

        Requires:
            User is an admin
        """

        await interaction.response.defer(ephemeral=True)

        allowed_roles = {"mentor", "judge", "participant", "mentor/judge"}
        if role not in allowed_roles:
            _log_rejection(interaction, "invalid_role", requested_role=role)
            await interaction.edit_original_response(
                content=f"`<{role}>` is not a valid role. Choose mentor, judge, participant, or mentor/judge.",
            )
            return

        roles_to_add = ["mentor", "judge"] if role == "mentor/judge" else [role]

        # Case 1: User is already verified (Add Role)
        if records.is_verified(member_to_promote.id):
            verified_email = records.get_verified_email(member_to_promote.id)

            roles = records.get_user_roles(verified_email)
            new_roles = [
                role_name for role_name in roles_to_add if role_name not in roles
            ]
            if not new_roles:
                await interaction.edit_original_response(
                    content=f"`<{member_to_promote.name}>` is verified and already has the role `<{role}>`.",
                )
                return

            roles.extend(new_roles)
            records.update_roles(verified_email, roles)

            await interaction.edit_original_response(
                content=f"`<{member_to_promote.name}>` is already verified but has been given the role `<{role}>`.",
            )

        # Case 2: User is not Verified (Register and Verify User with the appropriate roles)
        else:
            records.add_registration(
                email_address, first_name, last_name, is_capstone, roles_to_add
            )
            records.add_verified_user(
                email_address, member_to_promote.id, member_to_promote.name
            )
            await interaction.edit_original_response(
                content=f"`<{member_to_promote.name}>` has been verified and given the role `<{role}>`.",
            )

        # Assign the overified user any roles assigned
        await sync_user_roles(member_to_promote)

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(
        name="remove_team", description="Remove Team (Organizers only)"
    )
    @audit_command
    async def remove_team(
        self,
        interaction: discord.Interaction,
        team_role: discord.Role,
        reason_for_removal: str,
    ):  # TESTED
        """
        Delete a team and its associated data from the event.

        Args:
            ctxt (discord.Interaction): The Context of the Interaction
            flags (removeTeamFlag): Flags containing the 'team_role' and 'reason' for removal
        """
        await interaction.response.defer(ephemeral=True)

        # Retrieve team details before removal
        team_name = team_role.name
        team_data = records.get_team(team_name)
        if not team_data:
            _log_rejection(interaction, "team_not_found", team_name=team_name)
            await interaction.edit_original_response(
                content=f"The team `<{team_name}>` could not be found."
            )
            return
        team_id = team_data["id"]
        members = records.get_team_members(team_name)

        # ------------- Happy Case --------------------

        # Notify team and admin about removal
        for member in members:
            member_obj = interaction.guild.get_member(member["discord_id"])
            if not member_obj:
                continue
            await member_obj.send(
                content=f"Your team has been removed from the event. \nReason: `{reason_for_removal}`. \nYou may create a new team but continued failure to comply may result in being permanently removed"
            )

        await interaction.edit_original_response(
            content=f"The team `<{team_name}>` has been removed and the members have been notified"
        )

        # Remove channels and remove team stats from members
        await handle_team_deletion(team_id, interaction.guild)

    @app_commands.guild_only()
    @app_commands.checks.has_any_role(
        config.discord_organizer_role_id, config.discord_all_access_pass_role_id
    )  # Only Organizer or All-Access-Pass can View/Use
    @app_commands.describe(target="Select a Team Role OR a Team Member")
    @app_commands.command(
        name="find_channel", description="Get a quick link to a team's text channel"
    )
    @audit_command
    async def find_channel(
        self,
        interaction: discord.Interaction,
        target: Union[discord.Role, discord.Member],
    ):

        await interaction.response.defer(ephemeral=True)

        # Retrieve the Team_ID from role
        if isinstance(target, discord.Role):
            team_name = target.name

            # Check if role is associated with a team
            if not records.team_exists(team_name):
                _log_rejection(interaction, "team_not_found", team_name=team_name)
                await interaction.edit_original_response(
                    content=f"Team `{team_name}` cannot be found. Please use a role that is associated with a valid team",
                )
                return
            else:
                team_info = records.get_team(team_name)
                text_channel = interaction.guild.get_channel(team_info["text_id"])

        # Retrieve the Team_ID from user
        elif isinstance(target, discord.Member):
            member_id = target.id
            team_id = records.get_user_team_id(member_id)

            # Ensure User is on a Team
            if team_id is None:
                _log_rejection(interaction, "member_not_on_team", target=target)
                await interaction.edit_original_response(
                    content=f"User: {target.mention} is not assigned to a team. No channel can be found.",
                )
                return
            else:
                team_info = records.get_team(team_id)
                text_channel = interaction.guild.get_channel(team_info["text_id"])

        # Send the Message
        if text_channel:
            await interaction.edit_original_response(
                content=f"Team #{team_info['id']} - {team_info['name']}\nLink to the team's text channel: {text_channel.mention}",
            )
        else:
            await interaction.edit_original_response(
                content="Could not find a channel associated with that target :(",
            )

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(
        name="broadcast", description="Broadcast a message to each team channel"
    )
    @audit_command
    async def broadcast(self, interaction: discord.Interaction, message: str):
        """
        Broadcasts a message to each team's text channel.

        Args:
            interaction (discord.Interaction): The Context of the Interaction.
            message (str): The message to broadcast.
        """

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)

        teams = records.get_all_teams()
        attempted = succeeded = skipped = failed = 0
        for team in teams:
            attempted += 1
            team_text_channel = cast(
                discord.TextChannel, guild.get_channel(team.get("text_id"))
            )
            role_obj = guild.get_role(team.get("role_id"))
            if not role_obj:
                skipped += 1
                continue
            if team_text_channel:
                try:
                    await team_text_channel.send(
                        embed=create_embed(
                            title="📫 Broadcasted Message", description=message
                        )
                    )
                    succeeded += 1
                except Exception:
                    failed += 1
                    logger.exception(
                        "broadcast_channel_failed team_id=%r channel_id=%r",
                        team.get("id"),
                        team_text_channel.id,
                    )
            else:
                skipped += 1

        logger.info(
            "broadcast_completed interaction_id=%r guild_id=%r actor_id=%r attempted=%r succeeded=%r skipped=%r failed=%r",
            interaction.id,
            getattr(interaction.guild, "id", None),
            interaction.user.id,
            attempted,
            succeeded,
            skipped,
            failed,
        )

        await interaction.edit_original_response(
            content=(
                f"Broadcast complete: {succeeded} sent, {failed} failed, "
                f"{skipped} skipped."
            ),
        )

    @commands.hybrid_command(name="sync", description="Sync commands (Organizer Only)")
    @app_commands.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    @app_commands.describe(spec="Scope of the sync (Local, Global, or Clear)")
    @audit_command
    async def sync(self, ctx: commands.Context, spec: str):
        """
        Syncs the bot commands.
        Usage:
        /sync [spec]
          - local    : Copy global commands to current server (Instant Dev)
          - global   : Sync globally (Takes 1 hour)
          - clear    : Wipe local commands
        """

        await ctx.defer(ephemeral=True)

        if spec.lower() == "local":
            self.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await self.bot.tree.sync(guild=ctx.guild)
            logger.info(
                "command_sync_completed scope=%r count=%r guild_id=%r",
                "local",
                len(synced),
                getattr(ctx.guild, "id", None),
            )
            await ctx.send(
                f"✅ **Local Sync:** Copied and synced {len(synced)} commands to this server.",
            )
            return

        if spec.lower() == "global":
            synced = await self.bot.tree.sync()
            logger.info(
                "command_sync_completed scope=%r count=%r", "global", len(synced)
            )
            await ctx.send(
                f"🌎 **Global Sync:** Synced {len(synced)} commands globally. (Updates may take up to 1 hour).",
            )
            return

        if spec.lower() == "clear":
            self.bot.tree.clear_commands(guild=ctx.guild)
            await self.bot.tree.sync(guild=ctx.guild)
            logger.info(
                "command_sync_completed scope=%r guild_id=%r",
                "clear",
                getattr(ctx.guild, "id", None),
            )
            await ctx.send("🧹 Cleared guild-specific commands.")
            return
        logger.info(
            "command_rejected command=%r reason=%r scope=%r guild_id=%r actor_id=%r actor_username=%r",
            "sync",
            "invalid_scope",
            spec,
            getattr(ctx.guild, "id", None),
            getattr(ctx.author, "id", None),
            getattr(ctx.author, "name", None),
        )
        await ctx.send("Please provide a valid spec argument (local, global, clear)")


async def setup(bot: commands.Bot):
    await bot.add_cog(OrganizerCog(bot))
