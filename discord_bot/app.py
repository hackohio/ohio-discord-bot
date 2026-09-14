"""Application and lifecycle for the OHI/O Discord bot."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from discord_bot.common import _log_rejection
from logging_config import configure_logging

logger = logging.getLogger(__name__)

EXTENSIONS = (
    "discord_bot.cogs.cleanup",
    "discord_bot.cogs.lfg",
    "discord_bot.cogs.teams",
    "discord_bot.cogs.verification",
    "discord_bot.cogs.organizer",
)


class OhioBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.tree.on_error = self.on_application_command_error

    async def setup_hook(self):
        for extension in EXTENSIONS:
            await self.load_extension(extension)

    async def _send_safe_error_response(self, interaction: discord.Interaction):
        """Attempt one generic ephemeral response without exposing exception data."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    content="Something went wrong while processing that command.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    content="Something went wrong while processing that command.",
                    ephemeral=True,
                )
        except Exception:
            logger.exception(
                "error_response_failed interaction_id=%r",
                interaction.id,
            )

    async def on_application_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        original = getattr(error, "original", error)
        if isinstance(
            error, (app_commands.CheckFailure, app_commands.CommandOnCooldown)
        ):
            _log_rejection(interaction, type(error).__name__)
        else:
            command = interaction.command
            logger.error(
                "application_command_failed command=%r interaction_id=%r",
                command.qualified_name if command else None,
                interaction.id,
                exc_info=original,
            )
        await self._send_safe_error_response(interaction)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        original = getattr(error, "original", error)
        command = ctx.command
        logger.error(
            "hybrid_command_failed command=%r actor_id=%r",
            command.qualified_name if command else None,
            ctx.author.id,
            exc_info=original,
        )
        try:
            await ctx.send("Something went wrong while processing that command.")
        except Exception:
            logger.exception(
                "error_response_failed command=%r",
                command.qualified_name if command else None,
            )

    async def on_ready(self):
        user = self.user
        logger.info(
            "bot_ready bot_id=%r bot_username=%r guild_id=%r",
            user.id if user else None,
            user.name if user else None,
            config.discord_guild_id,
        )


def run_bot():
    configure_logging("bot")
    logger.info("bot_starting guild_id=%r", config.discord_guild_id)
    OhioBot().run(config.discord_token, log_handler=None)
