from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

import config
from discord_bot.cogs.cleanup import (
    NOTIFICATION_COOLDOWN,
    REMOVAL_DM,
    REMOVAL_NOTICE,
    CleanupCog,
)


class CleanupMessageTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._channel_ids = config.cleanup_channel_ids
        self._protected_ids = config.cleanup_protected_user_ids
        config.cleanup_channel_ids = {10}
        config.cleanup_protected_user_ids = {20}
        self.bot_user = SimpleNamespace(id=1)
        self.cog = CleanupCog(SimpleNamespace(user=self.bot_user))

    def tearDown(self):
        config.cleanup_channel_ids = self._channel_ids
        config.cleanup_protected_user_ids = self._protected_ids

    def author(self, user_id, *, roles=(), administrator=False, mention=None):
        return SimpleNamespace(
            id=user_id,
            mention=mention or f"<@{user_id}>",
            roles=list(roles),
            guild_permissions=SimpleNamespace(administrator=administrator),
            send=AsyncMock(),
        )

    def message(
        self,
        author,
        *,
        channel_id=10,
        guild_id=99,
        pinned=False,
        message_type=discord.MessageType.default,
        delete_failure=None,
    ):
        channel = SimpleNamespace(id=channel_id, send=AsyncMock())
        guild = SimpleNamespace(
            id=guild_id,
            get_member=lambda member_id: author if member_id == author.id else None,
        )
        return SimpleNamespace(
            id=50,
            author=author,
            channel=channel,
            guild=guild,
            pinned=pinned,
            is_system=lambda: message_type == discord.MessageType.recipient_add,
            delete=AsyncMock(side_effect=delete_failure),
        )

    async def test_messages_outside_configured_channels_and_dms_are_ignored(self):
        outside = self.message(self.author(2), channel_id=11)
        direct = self.message(self.author(3))
        direct.guild = None

        await self.cog.on_message(outside)
        await self.cog.on_message(direct)

        outside.delete.assert_not_awaited()
        direct.delete.assert_not_awaited()

    async def test_unprotected_message_is_deleted_and_author_is_notified(self):
        author = self.author(2)
        message = self.message(author)

        await self.cog.on_message(message)

        message.delete.assert_awaited_once_with()
        author.send.assert_awaited_once_with(content=REMOVAL_DM)
        message.channel.send.assert_not_awaited()

    async def test_exempt_messages_are_preserved(self):
        cases = (
            self.message(self.author(1)),
            self.message(self.author(2), pinned=True),
            self.message(self.author(3), message_type=discord.MessageType.recipient_add),
            self.message(self.author(20)),
            self.message(
                self.author(4, roles=[SimpleNamespace(id=config.discord_organizer_role_id)])
            ),
            self.message(self.author(5, administrator=True)),
        )

        for message in cases:
            with self.subTest(author_id=message.author.id):
                await self.cog.on_message(message)
                message.delete.assert_not_awaited()

    async def test_other_bots_are_deleted(self):
        author = self.author(6)
        author.bot = True
        message = self.message(author)

        await self.cog.on_message(message)

        message.delete.assert_awaited_once_with()

    async def test_failed_dm_sends_temporary_channel_notice(self):
        author = self.author(2)
        author.send.side_effect = OSError("DMs disabled")
        message = self.message(author)

        await self.cog.on_message(message)

        message.delete.assert_awaited_once_with()
        message.channel.send.assert_awaited_once_with(
            content=REMOVAL_NOTICE,
            delete_after=10,
        )

    async def test_failed_deletion_does_not_notify(self):
        author = self.author(2)
        message = self.message(author, delete_failure=OSError("missing permission"))

        await self.cog.on_message(message)

        author.send.assert_not_awaited()
        message.channel.send.assert_not_awaited()

    async def test_cooldown_only_suppresses_notifications(self):
        author = self.author(2)
        first = self.message(author)
        second = self.message(author)

        with patch(
            "discord_bot.cogs.cleanup.time.monotonic",
            side_effect=(100, 100 + NOTIFICATION_COOLDOWN - 1),
        ):
            await self.cog.on_message(first)
            await self.cog.on_message(second)

        first.delete.assert_awaited_once_with()
        second.delete.assert_awaited_once_with()
        self.assertEqual(author.send.await_count, 1)
        second.channel.send.assert_not_awaited()

    async def test_notification_failures_are_contained(self):
        author = self.author(2)
        author.send.side_effect = OSError("DMs disabled")
        message = self.message(author)
        message.channel.send.side_effect = OSError("missing permission")

        await self.cog.on_message(message)

        message.delete.assert_awaited_once_with()
