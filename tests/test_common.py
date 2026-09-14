from types import SimpleNamespace
import unittest

from discord.ext import commands

from discord_bot.common import audit_command


class AuditCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_audit_command_logs_cog_and_context_callbacks(self):
        class AuditCog(commands.Cog):
            def __init__(self):
                self.called = False

            @audit_command
            async def audit_app(self, interaction):
                self.called = True
                return "app result"

        @audit_command
        async def audit_hybrid(ctx):
            return "hybrid result"

        cog = AuditCog()
        guild = SimpleNamespace(id=99)
        interaction = SimpleNamespace(
            id=1,
            user=SimpleNamespace(id=7, name="app-user"),
            guild=guild,
        )
        context = SimpleNamespace(
            id=2,
            author=SimpleNamespace(id=8, name="hybrid-user"),
            guild=guild,
        )

        with self.assertLogs("discord_bot.common", level="INFO") as logs:
            self.assertEqual(await cog.audit_app(interaction), "app result")
            self.assertEqual(await audit_hybrid(context), "hybrid result")

        rendered = " ".join(logs.output)
        self.assertTrue(cog.called)
        self.assertIn("'actor_id': 7", rendered)
        self.assertIn("'actor_id': 8", rendered)
        self.assertIn("command_started", rendered)
        self.assertIn("command_finished", rendered)
