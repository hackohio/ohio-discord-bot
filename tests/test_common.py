from types import SimpleNamespace
import unittest

import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.common import audit_command


class AuditCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_audit_command_supports_cog_app_and_hybrid_commands(self):
        class AuditCog(commands.Cog):
            def __init__(self, bot):
                self.bot = bot
                self.app_called = False
                self.hybrid_called = False

            @app_commands.command(name="audit_app")
            @audit_command
            async def audit_app(self, interaction):
                self.app_called = True

            @commands.hybrid_command(name="audit_hybrid")
            @audit_command
            async def audit_hybrid(self, ctx):
                self.hybrid_called = True

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        try:
            cog = AuditCog(bot)
            await bot.add_cog(cog)
            actor = SimpleNamespace(id=7, name="tester")
            guild = SimpleNamespace(id=99)
            interaction = SimpleNamespace(id=1, user=actor, guild=guild)
            context = SimpleNamespace(id=2, author=actor, guild=guild)

            with self.assertLogs("discord_bot.common", level="INFO") as logs:
                await bot.tree.get_command("audit_app").callback(
                    cog, interaction
                )
                await bot.get_command("audit_hybrid").callback(cog, context)

            self.assertTrue(cog.app_called)
            self.assertTrue(cog.hybrid_called)
            self.assertIn("'actor_id': 7", " ".join(logs.output))
        finally:
            await bot.close()
