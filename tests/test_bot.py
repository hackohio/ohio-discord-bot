from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from tests.helpers import DatabaseTestMixin

import bot as bot_module
import config
import records


class FakeRole:
    def __init__(self, role_id):
        self.id = role_id


class FakeResource:
    def __init__(self, resource_id, *, failure=None):
        self.id = resource_id
        self.delete = AsyncMock(side_effect=failure)


class FakeGuild:
    def __init__(self, *, roles=None, channels=None, members=None):
        self.id = 99
        self._roles = roles or {}
        self._channels = channels or {}
        self._members = members or {}

    def get_role(self, role_id):
        return self._roles.get(role_id)

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)

    def get_member(self, member_id):
        return self._members.get(member_id)


def make_member(member_id, guild=None, name=None):
    name = name or f"user-{member_id}"
    return SimpleNamespace(
        id=member_id,
        name=name,
        display_name=name,
        mention=f"<@{member_id}>",
        guild=guild,
        roles=[],
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
    )


def make_interaction(user, guild=None, *, response_done=False):
    response = SimpleNamespace(
        defer=AsyncMock(),
        send_message=AsyncMock(),
        is_done=lambda: response_done,
    )
    followup = SimpleNamespace(send=AsyncMock())
    return SimpleNamespace(
        id=500,
        user=user,
        guild=guild or SimpleNamespace(id=99),
        response=response,
        followup=followup,
    )


class BotHelperTestCase(DatabaseTestMixin, unittest.IsolatedAsyncioTestCase):
    def test_lfg_commands_are_registered(self):
        group = bot_module.bot.tree.get_command("lfg")
        self.assertIsNotNone(group)
        self.assertEqual({command.name for command in group.commands}, {"toggle", "view"})

    def test_can_join_team_validation_codes(self):
        unverified = make_member(999)
        self.assertEqual(bot_module.can_join_team(unverified), -1)

        staff = make_member(100)
        self.add_verified(
            100, email="staff@example.com", roles=["mentor"], username="staff#0001"
        )
        self.assertEqual(bot_module.can_join_team(staff), -2)

        assigned = make_member(101)
        self.add_verified(101)
        team_id = records.create_team("Assigned", False, 201, 202, 203)
        records.join_team(101, team_id)
        self.assertEqual(bot_module.can_join_team(assigned), -3)

        capstone = make_member(102)
        self.add_verified(102, is_capstone=True)
        standard = make_member(103)
        self.add_verified(103, is_capstone=False)
        self.assertEqual(bot_module.can_join_team(capstone, False), -4)
        self.assertEqual(bot_module.can_join_team(standard, True), -4)
        self.assertEqual(bot_module.can_join_team(capstone, True), 0)
        self.assertEqual(bot_module.can_join_team(standard, False), 0)

    async def test_lfg_toggle_validates_and_toggles_skills(self):
        unverified_interaction = make_interaction(make_member(999))
        await bot_module.lfg_toggle.callback(unverified_interaction)
        self.assertIn("verify first", unverified_interaction.followup.send.call_args.kwargs["content"])

        self.add_verified(100, roles=["mentor"])
        staff_interaction = make_interaction(make_member(100))
        await bot_module.lfg_toggle.callback(staff_interaction)
        self.assertIn("participant", staff_interaction.followup.send.call_args.kwargs["content"])
        self.assertFalse(records.is_looking(100))

        self.add_verified(101)
        user = make_member(101)
        start_interaction = make_interaction(user)
        await bot_module.lfg_toggle.callback(start_interaction)
        self.assertTrue(records.is_looking(101))
        self.assertIn(
            "now marked", start_interaction.followup.send.call_args.kwargs["content"]
        )

        update_interaction = make_interaction(user)
        await bot_module.lfg_toggle.callback(update_interaction, "Python")
        self.assertEqual(records.get_lfg_list()[0]["skills"], "Python")
        self.assertIn("Updated your skills", update_interaction.followup.send.call_args.kwargs["content"])

        remove_interaction = make_interaction(user)
        await bot_module.lfg_toggle.callback(remove_interaction)
        self.assertFalse(records.is_looking(101))
        self.assertIn("no longer marked", remove_interaction.followup.send.call_args.kwargs["content"])

        self.add_verified(102)
        team_id = records.create_team("Team", False, 201, 202, 203)
        records.join_team(102, team_id)
        team_interaction = make_interaction(make_member(102))
        await bot_module.lfg_toggle.callback(team_interaction, "Rust")
        self.assertFalse(records.is_looking(102))
        self.assertIn("already on a team", team_interaction.followup.send.call_args.kwargs["content"])

    async def test_lfg_view_filters_absent_members_and_formats_skills(self):
        records.add_registration("alice@example.com", "Alice", "One", False, ["participant"])
        records.add_verified_user("alice@example.com", 101, "alice#0001")
        self.add_verified(102)
        records.add_registration(
            "nameless@example.com", None, "User", False, ["participant"]
        )
        records.add_verified_user("nameless@example.com", 103, "nameless#0001")
        records.add_to_lfg(101, "Python")
        records.add_to_lfg(102, "Go")
        records.add_to_lfg(103)

        guild = FakeGuild(
            members={101: make_member(101), 103: make_member(103)},
        )
        interaction = make_interaction(make_member(500), guild)
        await bot_module.lfg_view.callback(interaction)

        embed = interaction.followup.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "Looking for a Team (2)")
        self.assertIn("Alice", embed.description)
        self.assertIn("Python", embed.description)
        self.assertIn("nameless#0001", embed.description)
        self.assertIn("_No skills listed_", embed.description)
        self.assertNotIn("Go", embed.description)

    async def test_lfg_view_truncates_long_lists(self):
        for member_id in range(100, 130):
            self.add_verified(member_id)
            records.add_to_lfg(member_id, "x" * 150)

        guild = FakeGuild(
            members={member_id: make_member(member_id) for member_id in range(100, 130)},
        )
        interaction = make_interaction(make_member(500), guild)
        await bot_module.lfg_view.callback(interaction)

        description = interaction.followup.send.call_args.kwargs["embed"].description
        self.assertIn("...and", description)
        self.assertLess(description.count("> " + "x" * 150), 30)

    async def test_lfg_view_reports_empty_pool(self):
        interaction = make_interaction(make_member(500), FakeGuild())
        await bot_module.lfg_view.callback(interaction)
        embed = interaction.followup.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "Looking for a Team")
        self.assertIn("No one is currently looking", embed.description)

    async def test_sync_user_roles_adds_removes_and_noops(self):
        member_id = 101
        self.add_verified(
            member_id,
            email="person@example.com",
            roles=["participant", "mentor"],
        )
        roles = {role_id: FakeRole(role_id) for role_id in bot_module.role_map.values()}
        guild = FakeGuild(roles=roles)
        member = make_member(member_id, guild)
        member.roles = [roles[config.discord_judge_role_id]]

        await bot_module.sync_user_roles(member)

        member.add_roles.assert_awaited_once_with(
            roles[config.discord_participant_role_id],
            roles[config.discord_mentor_role_id],
            roles[config.discord_verified_role_id],
            roles[config.discord_all_access_pass_role_id],
        )
        member.remove_roles.assert_awaited_once_with(roles[config.discord_judge_role_id])

        member.add_roles.reset_mock()
        member.remove_roles.reset_mock()
        member.roles = [
            roles[config.discord_participant_role_id],
            roles[config.discord_mentor_role_id],
            roles[config.discord_verified_role_id],
            roles[config.discord_all_access_pass_role_id],
        ]
        await bot_module.sync_user_roles(member)
        member.add_roles.assert_not_awaited()
        member.remove_roles.assert_not_awaited()

    async def test_sync_user_roles_skips_missing_roles_and_unverified_members(self):
        self.add_verified(101)
        roles = {
            role_id: FakeRole(role_id)
            for role_id in bot_module.role_map.values()
            if role_id != config.discord_verified_role_id
        }
        guild = FakeGuild(roles=roles)
        member = make_member(101, guild)
        await bot_module.sync_user_roles(member)
        member.add_roles.assert_awaited_once_with(
            roles[config.discord_participant_role_id],
        )

        unverified = make_member(999, guild)
        await bot_module.sync_user_roles(unverified)
        unverified.add_roles.assert_not_awaited()
        unverified.remove_roles.assert_not_awaited()

    async def test_team_join_and_leave_update_database_and_roles(self):
        self.add_verified(101)
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        team_role = FakeRole(201)
        assigned_role = FakeRole(config.discord_team_assigned_role_id)
        guild = FakeGuild(roles={201: team_role, assigned_role.id: assigned_role})
        member = make_member(101, guild)
        records.add_to_lfg(101, "Python")

        with patch.object(bot_module.bot, "get_guild", return_value=guild):
            await bot_module.perform_team_join(member, team_id)
            self.assertEqual(records.get_user_team_id(101), team_id)
            self.assertFalse(records.is_looking(101))
            member.add_roles.assert_awaited_once_with(team_role, assigned_role)

            member.add_roles.reset_mock()
            await bot_module.perform_team_leave(member, team_id)

        self.assertIsNone(records.get_user_team_id(101))
        member.remove_roles.assert_awaited_once_with(team_role, assigned_role)

    async def test_team_deletion_removes_present_resources(self):
        self.add_verified(101)
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        records.join_team(101, team_id)
        member = make_member(101)
        resources = {
            202: FakeResource(202),
            203: FakeResource(203),
            204: FakeResource(204),
        }
        roles = {201: FakeResource(201)}
        guild = FakeGuild(roles=roles, channels=resources, members={101: member})

        with patch.object(bot_module.bot, "get_guild", return_value=guild):
            await bot_module.handle_team_deletion(team_id)

        self.assertFalse(records.team_exists(team_id))
        self.assertIsNone(records.get_user_team_id(101))
        for resource in (*resources.values(), *roles.values()):
            resource.delete.assert_awaited_once()
        member.remove_roles.assert_awaited_once()

    async def test_team_channel_deletion_skips_missing_and_surfaces_failures(self):
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        text = FakeResource(203)
        guild = FakeGuild(channels={203: text}, roles={})
        with patch.object(bot_module.bot, "get_guild", return_value=guild):
            await bot_module.delete_team_channels(team_id)
        text.delete.assert_awaited_once()

        deleted_text = FakeResource(203)
        failing_voice = FakeResource(204, failure=OSError("discord unavailable"))
        guild = FakeGuild(channels={203: deleted_text, 204: failing_voice}, roles={})
        with patch.object(bot_module.bot, "get_guild", return_value=guild):
            with self.assertRaises(OSError):
                await bot_module.delete_team_channels(team_id)
        deleted_text.delete.assert_awaited_once()
        failing_voice.delete.assert_awaited_once()

    async def test_safe_error_response_uses_initial_response_or_followup(self):
        initial = make_interaction(make_member(101))
        await bot_module._send_safe_error_response(initial)
        initial.response.send_message.assert_awaited_once_with(
            content="Something went wrong while processing that command.", ephemeral=True
        )
        initial.followup.send.assert_not_awaited()

        followup = make_interaction(make_member(101), response_done=True)
        await bot_module._send_safe_error_response(followup)
        followup.followup.send.assert_awaited_once_with(
            content="Something went wrong while processing that command.", ephemeral=True
        )
        followup.response.send_message.assert_not_awaited()

    async def test_verify_rejects_expired_code_and_wrong_owner(self):
        user = make_member(101)
        interaction = make_interaction(user)
        self.add_verified(202, email="other@example.com")
        records.add_registration(
            "person@example.com", "Pat", "One", False, ["participant"]
        )
        with patch("records.time.time", return_value=100.0) as clock:
            records.add_code("person@example.com", 101, "123456", 10)
            clock.return_value = 110.0
            await bot_module.verify.callback(interaction, "123456")
        self.assertIn("not valid or has expired", interaction.followup.send.call_args.kwargs["content"])

        records.add_code("person@example.com", 202, "654321", 600)
        wrong_owner = make_interaction(user)
        await bot_module.verify.callback(wrong_owner, "654321")
        self.assertIn("not associated", wrong_owner.followup.send.call_args.kwargs["content"])

    async def test_verify_success_links_user_removes_code_and_syncs_roles(self):
        user = make_member(101)
        self.add_verified(202, email="already@example.com")
        records.add_registration(
            "person@example.com", "Pat", "One", False, ["participant"]
        )
        records.add_code("person@example.com", 101, "123456", 600)
        start_channel = SimpleNamespace(mention="#start-here")
        guild = SimpleNamespace(
            id=99,
            get_channel=lambda channel_id: start_channel,
        )
        interaction = make_interaction(user, guild)

        with (
            patch.object(bot_module, "sync_user_roles", new=AsyncMock()) as sync_roles,
            patch.object(bot_module.bot, "get_guild", return_value=guild),
        ):
            await bot_module.verify.callback(interaction, "123456")

        self.assertTrue(records.is_verified(101))
        self.assertFalse(records.code_exists("123456"))
        sync_roles.assert_awaited_once_with(user)
        self.assertIn("Welcome Pat", interaction.followup.send.call_args.kwargs["content"])

    async def test_verification_email_failure_is_safe(self):
        self.add_verified(101, email="person@example.com")
        with patch.object(
            bot_module.smtplib, "SMTP_SSL", side_effect=OSError("smtp unavailable")
        ):
            self.assertFalse(
                await bot_module.send_verification_email(
                    "person@example.com", "123456", "person#0001"
                )
            )
