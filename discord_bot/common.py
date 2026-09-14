"""Helpers shared by Discord cogs."""

import functools
import logging
import time

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)
OHIO_RED = discord.Color.from_rgb(186, 12, 47)


def create_embed(title: str, description: str, color=OHIO_RED) -> discord.Embed:
    """Build an embed with the event's standard color."""
    return discord.Embed(title=title, description=description, color=color)


def _command_context(args):
    """Return the interaction/context after an optional Cog instance."""
    if args and isinstance(args[0], commands.Cog):
        return args[1]
    return args[0]


def _log_rejection(
    interaction: discord.Interaction,
    reason: str,
    *,
    target: discord.Member | None = None,
    **fields,
):
    """Log the shared command-rejection event schema."""
    command = getattr(interaction, "command", None)
    user = getattr(interaction, "user", None) or getattr(interaction, "author", None)
    logger.info(
        "command_rejected command=%r interaction_id=%r guild_id=%r "
        "actor_id=%r actor_username=%r reason=%r target_id=%r "
        "target_username=%r details=%r",
        getattr(command, "qualified_name", None) or "unknown",
        getattr(interaction, "id", None),
        getattr(getattr(interaction, "guild", None), "id", None),
        getattr(user, "id", None),
        getattr(user, "name", None),
        reason,
        getattr(target, "id", None),
        getattr(target, "name", None),
        fields,
    )


def audit_command(callback):
    """Log command start and completion for app and hybrid Cog commands."""

    @functools.wraps(callback)
    async def audited(*args, **kwargs):
        invocation = _command_context(args)
        user = getattr(invocation, "user", None) or getattr(
            invocation, "author", None
        )
        guild = getattr(invocation, "guild", None)
        fields = {
            "command": callback.__name__,
            "interaction_id": getattr(invocation, "id", None),
            "guild_id": getattr(guild, "id", None),
            "actor_id": getattr(user, "id", None),
            "actor_username": getattr(user, "name", None),
        }
        started_at = time.monotonic()
        logger.info("command_started details=%r", fields)
        result = await callback(*args, **kwargs)
        logger.info(
            "command_finished details=%r duration_ms=%r",
            fields,
            round((time.monotonic() - started_at) * 1000, 3),
        )
        return result

    return audited
