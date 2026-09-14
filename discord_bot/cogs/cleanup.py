"""Remove ordinary messages from configured channels."""

import logging
import time

import discord
from discord.ext import commands

import config

logger = logging.getLogger(__name__)

NOTIFICATION_COOLDOWN = 30
REMOVAL_DM = (
    "Your message was removed because normal messages are not allowed in that "
    "channel. Please use the appropriate slash command, such as `/verify`."
    "Reach out to `#ask-an-organizer` if you think this was a mistake."
)
REMOVAL_NOTICE = (
    "Normal messages are not allowed here. Please use the appropriate slash "
    "command. Reach out in `#ask-in-organizer` if you think this was a mistake."
)


class CleanupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_notification_at: dict[int, float] = {}

    def _is_exempt(self, message: discord.Message) -> bool:
        author = message.author
        if self.bot.user is not None and author.id == self.bot.user.id:
            return True
        if message.pinned or message.is_system():
            return True
        if author.id in config.cleanup_protected_user_ids:
            return True

        member = (
            author
            if isinstance(author, discord.Member)
            else message.guild.get_member(author.id)
        )
        if member is None:
            return False
        return member.guild_permissions.administrator or any(
            role.id == config.discord_organizer_role_id for role in member.roles
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.channel.id not in config.cleanup_channel_ids:
            return
        if self._is_exempt(message):
            return

        author = message.author
        fields = {
            "guild_id": message.guild.id,
            "channel_id": message.channel.id,
            "message_id": message.id,
            "author_id": author.id,
        }
        try:
            await message.delete()
        except Exception:
            logger.exception("cleanup_message_deletion_failed details=%r", fields)
            return

        logger.info("cleanup_message_deleted details=%r", fields)
        now = time.monotonic()
        last_notification = self._last_notification_at.get(author.id)
        if (
            last_notification is not None
            and now - last_notification < NOTIFICATION_COOLDOWN
        ):
            return
        self._last_notification_at[author.id] = now

        try:
            await author.send(content=REMOVAL_DM)
            logger.info("cleanup_notification_dm_sent details=%r", fields)
        except Exception:
            logger.exception("cleanup_notification_dm_failed details=%r", fields)
            try:
                await message.channel.send(
                    content=REMOVAL_NOTICE,
                    delete_after=10,
                )
            except Exception:
                logger.exception(
                    "cleanup_notification_fallback_failed details=%r", fields
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(CleanupCog(bot))
