import asyncio
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import AsyncMock, patch

from tests.helpers import DatabaseTestMixin

from discord_bot.app import EXTENSIONS, OhioBot
from discord_bot.cogs import lfg, teams, verification

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
        send=AsyncMock(),
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
        command=None,
        response=response,
        edit_original_response=AsyncMock(),
        followup=followup,
    )


def lfg_callback(cog, interaction, *args):
    return lfg.LfgCog.lfg_toggle.callback(cog, interaction, *args)


def lfg_view_callback(cog, interaction):
    return lfg.LfgCog.lfg_view.callback(cog, interaction)


def verification_callback(cog, interaction, *args):
    return verification.VerificationCog.verify.callback(cog, interaction, *args)


class BotHelperTestCase(DatabaseTestMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        bot = SimpleNamespace()
        self.lfg_cog = lfg.LfgCog(bot)
        self.verification_cog = verification.VerificationCog(bot)

    def assert_deferred_response(self, interaction):
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.edit_original_response.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()

    def make_team(self, member_ids, *, lead=None, grace_period=None):
        members = {member_id: make_member(member_id) for member_id in member_ids}
        for member_id in member_ids:
            self.add_verified(member_id)
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        for member_id in member_ids:
            records.join_team(member_id, team_id)
        if member_ids:
            records.set_team_lead(team_id, lead if lead is not None else member_ids[0])
        if grace_period is not None:
            records.set_grace_period(team_id, grace_period)

        team_role = FakeResource(201)
        team_role.name = "Team"
        text_channel = FakeResource(203)
        text_channel.send = AsyncMock()
        voice_channel = FakeResource(204)
        category_channel = FakeResource(202)
        guild = FakeGuild(
            roles={
                201: team_role,
                config.discord_team_assigned_role_id: FakeRole(
                    config.discord_team_assigned_role_id
                ),
            },
            channels={202: category_channel, 203: text_channel, 204: voice_channel},
            members=members,
        )
        for member in members.values():
            member.guild = guild
        return team_id, guild, members, text_channel

    async def run_grace_period_cleanup(self, guild):
        bot = SimpleNamespace(get_guild=lambda guild_id: guild)
        cog = teams.TeamsCog(bot)
        await cog.cleanup_team_grace_periods.coro(cog)

    def test_can_join_team_validation_codes(self):
        unverified = make_member(999)
        self.assertEqual(teams.can_join_team(unverified), teams.TeamJoinStatus.NOT_VERIFIED)

        staff = make_member(100)
        self.add_verified(
            100, email="staff@example.com", roles=["mentor"], username="staff#0001"
        )
        self.assertEqual(teams.can_join_team(staff), teams.TeamJoinStatus.NOT_PARTICIPANT)

        assigned = make_member(101)
        self.add_verified(101)
        team_id = records.create_team("Assigned", False, 201, 202, 203)
        records.join_team(101, team_id)
        self.assertEqual(teams.can_join_team(assigned), teams.TeamJoinStatus.ALREADY_ON_TEAM)

        capstone = make_member(102)
        self.add_verified(102, is_capstone=True)
        standard = make_member(103)
        self.add_verified(103, is_capstone=False)
        self.assertEqual(
            teams.can_join_team(capstone, False), teams.TeamJoinStatus.CAPSTONE_MISMATCH
        )
        self.assertEqual(
            teams.can_join_team(standard, True), teams.TeamJoinStatus.CAPSTONE_MISMATCH
        )
        self.assertEqual(teams.can_join_team(capstone, True), teams.TeamJoinStatus.ALLOWED)
        self.assertEqual(teams.can_join_team(standard, False), teams.TeamJoinStatus.ALLOWED)

    async def test_create_team_rejects_invalid_creator_with_original_response(self):
        interaction = make_interaction(make_member(999))
        cog = teams.TeamsCog(SimpleNamespace())

        await teams.TeamsCog.create_team.callback(
            cog, interaction, "New Team", make_member(100)
        )

        self.assertIn(
            "not verified",
            interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(interaction)

    async def test_create_team_rejects_any_invalid_teammate(self):
        creator = make_member(101)
        valid_teammate = make_member(102)
        self.add_verified(creator.id)
        self.add_verified(valid_teammate.id)
        interaction = make_interaction(creator)
        cog = teams.TeamsCog(SimpleNamespace())

        await teams.TeamsCog.create_team.callback(
            cog, interaction, "New Team", make_member(999), valid_teammate
        )

        embed = interaction.edit_original_response.call_args.kwargs["embed"]
        self.assertIn("<@999> is not a verified participant", embed.description)
        self.assertIn("No team was created", embed.description)
        self.assertFalse(records.team_exists("New Team"))
        self.assertIsNone(records.get_user_team_id(valid_teammate.id))
        self.assert_deferred_response(interaction)

    async def test_create_team_succeeds_without_validation_warnings(self):
        creator = make_member(101)
        teammate = make_member(102)
        self.add_verified(creator.id)
        self.add_verified(teammate.id)

        team_role = FakeRole(201)
        team_role.mention = "<@&201>"
        text_channel = SimpleNamespace(
            id=203, mention="#new-team", send=AsyncMock()
        )
        voice_channel = SimpleNamespace(id=204)
        category = SimpleNamespace(
            id=202,
            create_text_channel=AsyncMock(return_value=text_channel),
            create_voice_channel=AsyncMock(return_value=voice_channel),
        )
        roles = {
            config.discord_all_access_pass_role_id: FakeRole(
                config.discord_all_access_pass_role_id
            ),
            config.discord_team_assigned_role_id: FakeRole(
                config.discord_team_assigned_role_id
            ),
            team_role.id: team_role,
        }
        guild = SimpleNamespace(
            id=99,
            default_role=FakeRole(0),
            get_role=roles.get,
            create_role=AsyncMock(return_value=team_role),
            create_category_channel=AsyncMock(return_value=category),
        )
        interaction = make_interaction(creator, guild)
        cog = teams.TeamsCog(SimpleNamespace())

        await teams.TeamsCog.create_team.callback(cog, interaction, "New Team", teammate)

        embed = interaction.edit_original_response.call_args.kwargs["embed"]
        self.assertIn("Team created", embed.title)
        self.assertIn("Team channel: #new-team", embed.description)
        self.assertEqual(records.get_user_team_id(creator.id), 1)
        self.assertEqual(records.get_user_team_id(teammate.id), 1)
        self.assert_deferred_response(interaction)

    async def test_create_team_rolls_back_if_teammate_is_claimed_during_setup(self):
        creator = make_member(101)
        teammate = make_member(102)
        self.add_verified(creator.id)
        self.add_verified(teammate.id)
        self.add_verified(103)
        old_team_id = records.create_team("Old Team", False, 301, 302, 303)
        records.join_team(103, old_team_id)

        team_role = FakeResource(201)
        team_role.mention = "<@&201>"
        text_channel = FakeResource(203)
        text_channel.mention = "#new-team"
        text_channel.send = AsyncMock()
        voice_channel = FakeResource(204)
        category = FakeResource(202)
        category.create_text_channel = AsyncMock(return_value=text_channel)
        category.create_voice_channel = AsyncMock(return_value=voice_channel)

        def claim_teammate(*args, **kwargs):
            records.join_team(teammate.id, old_team_id)
            return category

        roles = {
            config.discord_all_access_pass_role_id: FakeRole(
                config.discord_all_access_pass_role_id
            ),
            config.discord_team_assigned_role_id: FakeRole(
                config.discord_team_assigned_role_id
            ),
            team_role.id: team_role,
        }
        channels = {202: category, 203: text_channel, 204: voice_channel}
        members = {creator.id: creator, teammate.id: teammate}
        guild = SimpleNamespace(
            id=99,
            default_role=FakeRole(0),
            get_role=roles.get,
            get_channel=channels.get,
            get_member=members.get,
            create_role=AsyncMock(return_value=team_role),
            create_category_channel=AsyncMock(side_effect=claim_teammate),
        )
        creator.guild = guild
        teammate.guild = guild
        interaction = make_interaction(creator, guild)

        await teams.TeamsCog.create_team.callback(
            teams.TeamsCog(SimpleNamespace()), interaction, "New Team", teammate
        )

        self.assertEqual(records.get_user_team_id(teammate.id), old_team_id)
        self.assertEqual(records.get_team_size(old_team_id), 2)
        self.assertIsNone(records.get_team(old_team_id)["grace_period"])
        self.assertIsNone(records.get_user_team_id(creator.id))
        self.assertFalse(records.team_exists("New Team"))
        self.assertIn(
            "No team was created",
            interaction.edit_original_response.call_args.kwargs["content"],
        )
        teammate.add_roles.assert_not_awaited()
        creator.remove_roles.assert_awaited_once()
        for resource in (team_role, text_channel, voice_channel, category):
            resource.delete.assert_awaited_once()

    async def test_create_team_rejects_duplicate_teammates(self):
        creator = make_member(101)
        teammate = make_member(102)
        self.add_verified(creator.id)
        self.add_verified(teammate.id)
        interaction = make_interaction(creator)
        cog = teams.TeamsCog(SimpleNamespace())

        await teams.TeamsCog.create_team.callback(
            cog, interaction, "New Team", teammate, teammate
        )

        embed = interaction.edit_original_response.call_args.kwargs["embed"]
        self.assertIn("selected more than once", embed.description)
        self.assertFalse(records.team_exists("New Team"))
        self.assert_deferred_response(interaction)

    async def test_create_team_cleans_up_when_channel_creation_fails(self):
        creator = make_member(101)
        teammate = make_member(102)
        self.add_verified(creator.id)
        self.add_verified(teammate.id)

        team_role = FakeRole(201)
        team_role.delete = AsyncMock()
        roles = {
            config.discord_all_access_pass_role_id: FakeRole(
                config.discord_all_access_pass_role_id
            )
        }
        guild = SimpleNamespace(
            id=99,
            default_role=FakeRole(0),
            get_role=roles.get,
            create_role=AsyncMock(return_value=team_role),
            create_category_channel=AsyncMock(
                side_effect=OSError("Discord unavailable")
            ),
        )
        interaction = make_interaction(creator, guild)
        cog = teams.TeamsCog(SimpleNamespace())

        await teams.TeamsCog.create_team.callback(cog, interaction, "New Team", teammate)

        team_role.delete.assert_awaited_once()
        self.assertIn(
            "No team was created",
            interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assertFalse(records.team_exists("New Team"))
        self.assert_deferred_response(interaction)

    async def test_lfg_toggle_validates_and_toggles_skills(self):
        unverified_interaction = make_interaction(make_member(999))
        await lfg_callback(self.lfg_cog, unverified_interaction)
        self.assertIn(
            "verify first",
            unverified_interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(unverified_interaction)

        self.add_verified(100, roles=["mentor"])
        staff_interaction = make_interaction(make_member(100))
        await lfg_callback(self.lfg_cog, staff_interaction)
        self.assertIn(
            "participant",
            staff_interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(staff_interaction)
        self.assertFalse(records.is_looking(100))

        self.add_verified(101)
        user = make_member(101)
        start_interaction = make_interaction(user)
        await lfg_callback(self.lfg_cog, start_interaction)
        self.assertTrue(records.is_looking(101))
        self.assertIn(
            "now marked",
            start_interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(start_interaction)

        update_interaction = make_interaction(user)
        await lfg_callback(self.lfg_cog, update_interaction, "Python")
        self.assertEqual(records.get_lfg_list()[0]["skills"], "Python")
        self.assertIn(
            "Updated your skills",
            update_interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(update_interaction)

        remove_interaction = make_interaction(user)
        await lfg_callback(self.lfg_cog, remove_interaction)
        self.assertFalse(records.is_looking(101))
        self.assertIn(
            "no longer marked",
            remove_interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(remove_interaction)

        self.add_verified(102)
        team_id = records.create_team("Team", False, 201, 202, 203)
        records.join_team(102, team_id)
        team_interaction = make_interaction(make_member(102))
        await lfg_callback(self.lfg_cog, team_interaction, "Rust")
        self.assertFalse(records.is_looking(102))
        self.assertIn(
            "already on a team",
            team_interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(team_interaction)

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
        await lfg_view_callback(self.lfg_cog, interaction)

        embed = interaction.edit_original_response.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "Looking for a Team (2)")
        self.assertIn("Alice", embed.description)
        self.assertIn("Python", embed.description)
        self.assertIn("nameless#0001", embed.description)
        self.assertIn("_No skills listed_", embed.description)
        self.assertNotIn("Go", embed.description)
        self.assert_deferred_response(interaction)

    async def test_lfg_view_truncates_long_lists(self):
        for member_id in range(100, 130):
            self.add_verified(member_id)
            records.add_to_lfg(member_id, "x" * 150)

        guild = FakeGuild(
            members={member_id: make_member(member_id) for member_id in range(100, 130)},
        )
        interaction = make_interaction(make_member(500), guild)
        await lfg_view_callback(self.lfg_cog, interaction)

        description = interaction.edit_original_response.call_args.kwargs["embed"].description
        self.assertIn("...and", description)
        self.assertLess(description.count("> " + "x" * 150), 30)
        self.assert_deferred_response(interaction)

    async def test_lfg_view_reports_empty_pool(self):
        interaction = make_interaction(make_member(500), FakeGuild())
        await lfg_view_callback(self.lfg_cog, interaction)
        embed = interaction.edit_original_response.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "Looking for a Team")
        self.assertIn("No one is currently looking", embed.description)
        self.assert_deferred_response(interaction)

    async def test_sync_user_roles_adds_removes_and_noops(self):
        member_id = 101
        self.add_verified(
            member_id,
            email="person@example.com",
            roles=["participant", "mentor"],
        )
        roles = {role_id: FakeRole(role_id) for role_id in verification.role_map.values()}
        guild = FakeGuild(roles=roles)
        member = make_member(member_id, guild)
        member.roles = [roles[config.discord_judge_role_id]]

        await verification.sync_user_roles(member)

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
        await verification.sync_user_roles(member)
        member.add_roles.assert_not_awaited()
        member.remove_roles.assert_not_awaited()

    async def test_sync_user_roles_skips_missing_roles_and_unverified_members(self):
        self.add_verified(101)
        roles = {
            role_id: FakeRole(role_id)
            for role_id in verification.role_map.values()
            if role_id != config.discord_verified_role_id
        }
        guild = FakeGuild(roles=roles)
        member = make_member(101, guild)
        await verification.sync_user_roles(member)
        member.add_roles.assert_awaited_once_with(
            roles[config.discord_participant_role_id],
        )

        unverified = make_member(999, guild)
        await verification.sync_user_roles(unverified)
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

        await teams.perform_team_join(member, team_id, guild)
        self.assertEqual(records.get_user_team_id(101), team_id)
        self.assertFalse(records.is_looking(101))
        member.add_roles.assert_awaited_once_with(
            team_role, assigned_role, atomic=False
        )

        member.add_roles.reset_mock()
        await teams.perform_team_leave(member, team_id, guild)

        self.assertIsNone(records.get_user_team_id(101))
        member.remove_roles.assert_awaited_once_with(
            team_role, assigned_role, atomic=False
        )

    async def test_failed_team_role_addition_rolls_back_membership(self):
        self.add_verified(101)
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        team_role = FakeRole(201)
        assigned_role = FakeRole(config.discord_team_assigned_role_id)
        guild = FakeGuild(roles={201: team_role, assigned_role.id: assigned_role})
        member = make_member(101, guild)
        member.add_roles.side_effect = OSError("Discord unavailable")
        records.add_to_lfg(101, "Python")

        with self.assertRaises(OSError):
            await teams.perform_team_join(member, team_id, guild)

        self.assertIsNone(records.get_user_team_id(101))
        self.assertTrue(records.is_looking(101))
        member.add_roles.assert_awaited_once_with(
            team_role, assigned_role, atomic=False
        )

    async def test_failed_team_role_removal_restores_membership(self):
        self.add_verified(101)
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        records.join_team(101, team_id)
        team_role = FakeRole(201)
        assigned_role = FakeRole(config.discord_team_assigned_role_id)
        guild = FakeGuild(roles={201: team_role, assigned_role.id: assigned_role})
        member = make_member(101, guild)
        member.remove_roles.side_effect = OSError("Discord unavailable")

        with self.assertRaises(OSError):
            await teams.perform_team_leave(member, team_id, guild)

        self.assertEqual(records.get_user_team_id(101), team_id)
        member.remove_roles.assert_awaited_once_with(
            team_role, assigned_role, atomic=False
        )

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

        await teams.handle_team_deletion(team_id, guild)

        self.assertFalse(records.team_exists(team_id))
        self.assertIsNone(records.get_user_team_id(101))
        for resource in (*resources.values(), *roles.values()):
            resource.delete.assert_awaited_once()
        member.remove_roles.assert_awaited_once()

    async def test_lead_leaving_two_person_team_deletes_it_immediately(self):
        team_id, guild, members, _ = self.make_team([101, 102], lead=101)
        interaction = make_interaction(members[101], guild)

        await teams.TeamsCog.leave_team.callback(
            teams.TeamsCog(SimpleNamespace()), interaction
        )

        self.assertFalse(records.team_exists(team_id))
        members[102].send.assert_awaited_once()
        self.assertIn(
            "team was deleted",
            interaction.edit_original_response.call_args.kwargs["content"],
        )

    async def test_non_lead_leaving_two_person_team_starts_grace_period(self):
        team_id, guild, members, text_channel = self.make_team([101, 102], lead=101)
        interaction = make_interaction(members[102], guild)

        with patch("discord_bot.cogs.teams.time.time", return_value=100.0):
            await teams.TeamsCog.leave_team.callback(
                teams.TeamsCog(SimpleNamespace()), interaction
            )

        self.assertTrue(records.team_exists(team_id))
        self.assertEqual(records.get_team_size(team_id), 1)
        self.assertEqual(records.get_team(team_id)["grace_period"], 400.0)
        warning = text_channel.send.call_args_list[0].kwargs["content"]
        self.assertIn("<t:400:F>", warning)
        self.assertIn("Add another member before", warning)

    async def test_lead_removing_other_member_starts_grace_period(self):
        team_id, guild, members, text_channel = self.make_team([101, 102], lead=101)
        interaction = make_interaction(members[101], guild)

        with patch("discord_bot.cogs.teams.time.time", return_value=100.0):
            await teams.TeamsCog.remove_member.callback(
                teams.TeamsCog(SimpleNamespace()), interaction, members[102]
            )

        self.assertTrue(records.team_exists(team_id))
        self.assertEqual(records.get_team(team_id)["grace_period"], 400.0)
        self.assertTrue(
            any(
                call.kwargs.get("content", "").startswith(
                    "Your team now has fewer than two members."
                )
                for call in text_channel.send.call_args_list
            )
        )

    async def test_adding_second_member_cancels_pending_deletion(self):
        team_id, guild, members, text_channel = self.make_team(
            [101], lead=101, grace_period=123.0
        )
        self.add_verified(102)
        members[102] = make_member(102, guild)
        guild._members[102] = members[102]
        interaction = make_interaction(members[101], guild)

        await teams.TeamsCog.add_member.callback(
            teams.TeamsCog(SimpleNamespace()), interaction, members[102]
        )

        self.assertIsNone(records.get_team(team_id)["grace_period"])
        self.assertTrue(
            any(
                call.kwargs.get("content")
                == "Your team has at least two members again. Pending deletion has been cancelled."
                for call in text_channel.send.call_args_list
            )
        )

    async def test_singleton_team_is_deleted_after_deadline(self):
        team_id, guild, members, _ = self.make_team([101], lead=101, grace_period=99.0)

        await self.run_grace_period_cleanup(guild)

        self.assertFalse(records.team_exists(team_id))
        members[101].send.assert_awaited_once()

    async def test_recovered_team_is_not_deleted_by_cleanup(self):
        team_id, guild, _, _ = self.make_team([101, 102], lead=101, grace_period=99.0)

        await self.run_grace_period_cleanup(guild)

        self.assertTrue(records.team_exists(team_id))
        self.assertIsNone(records.get_team(team_id)["grace_period"])

    async def test_cleanup_rechecks_team_after_deletion_dm(self):
        team_id, guild, members, _ = self.make_team(
            [101], lead=101, grace_period=99.0
        )
        self.add_verified(102)

        def recover_team(*args, **kwargs):
            records.join_team(102, team_id)

        members[101].send.side_effect = recover_team

        await self.run_grace_period_cleanup(guild)

        self.assertTrue(records.team_exists(team_id))
        self.assertEqual(records.get_team_size(team_id), 2)
        self.assertIsNone(records.get_team(team_id)["grace_period"])
        guild.get_role(201).delete.assert_not_awaited()

    async def test_cleanup_rechecks_extended_deadline_after_deletion_dm(self):
        team_id, guild, members, _ = self.make_team(
            [101], lead=101, grace_period=99.0
        )
        members[101].send.side_effect = lambda **kwargs: records.set_grace_period(
            team_id, 200.0
        )

        with patch("discord_bot.cogs.teams.time.time", return_value=100.0):
            await self.run_grace_period_cleanup(guild)

        self.assertTrue(records.team_exists(team_id))
        self.assertEqual(records.get_team(team_id)["grace_period"], 200.0)
        guild.get_role(201).delete.assert_not_awaited()

    async def test_concurrent_team_deletions_are_serialized(self):
        team_id, guild, members, _ = self.make_team([101], lead=101)
        deletion_started = asyncio.Event()
        allow_deletion = asyncio.Event()

        async def pause_role_removal(*args, **kwargs):
            deletion_started.set()
            await allow_deletion.wait()

        members[101].remove_roles.side_effect = pause_role_removal
        first = asyncio.create_task(teams.handle_team_deletion(team_id, guild))
        await deletion_started.wait()
        second = asyncio.create_task(teams.handle_team_deletion(team_id, guild))
        await asyncio.sleep(0)
        allow_deletion.set()

        results = await asyncio.gather(first, second, return_exceptions=True)

        self.assertEqual(results, [None, None])
        self.assertFalse(records.team_exists(team_id))
        guild.get_role(201).delete.assert_awaited_once()

    async def test_empty_team_is_deleted_immediately(self):
        team_id, guild, _, _ = self.make_team([])

        deleted = await teams.enforce_team_size_policy(team_id, guild)

        self.assertTrue(deleted)
        self.assertFalse(records.team_exists(team_id))

    async def test_lead_leaving_larger_team_transfers_leadership(self):
        team_id, guild, members, _ = self.make_team([101, 102, 103], lead=101)
        interaction = make_interaction(members[101], guild)

        await teams.TeamsCog.leave_team.callback(
            teams.TeamsCog(SimpleNamespace()), interaction
        )

        team = records.get_team(team_id)
        self.assertTrue(records.team_exists(team_id))
        self.assertEqual(records.get_team_size(team_id), 2)
        self.assertIn(team["team_lead"], {102, 103})
        self.assertIsNone(team["grace_period"])

    async def test_failed_cleanup_remains_eligible_for_retry(self):
        team_id, guild, members, _ = self.make_team(
            [101], lead=101, grace_period=99.0
        )
        members[101].remove_roles.side_effect = OSError("Discord unavailable")

        await self.run_grace_period_cleanup(guild)

        self.assertTrue(records.team_exists(team_id))
        self.assertEqual(records.get_user_team_id(101), team_id)
        self.assertEqual(len(records.get_all_grace_periods()), 1)

    async def test_organizer_removal_stays_immediate(self):
        from discord_bot.cogs import organizer

        team_id, guild, members, _ = self.make_team([101, 102], lead=101)
        interaction = make_interaction(members[101], guild)

        await organizer.OrganizerCog.remove_team.callback(
            organizer.OrganizerCog(SimpleNamespace()),
            interaction,
            guild.get_role(201),
            "cleanup",
        )

        self.assertFalse(records.team_exists(team_id))
        self.assertIsNone(records.get_user_team_id(101))
        self.assertIsNone(records.get_user_team_id(102))

    async def test_team_channel_deletion_skips_missing_and_surfaces_failures(self):
        team_id = records.create_team("Team", False, 201, 202, 203, 204)
        text = FakeResource(203)
        guild = FakeGuild(channels={203: text}, roles={})
        await teams.delete_team_channels(team_id, guild)
        text.delete.assert_awaited_once()

        deleted_text = FakeResource(203)
        failing_voice = FakeResource(204, failure=OSError("discord unavailable"))
        guild = FakeGuild(channels={203: deleted_text, 204: failing_voice}, roles={})
        with self.assertRaises(OSError):
            await teams.delete_team_channels(team_id, guild)
        deleted_text.delete.assert_awaited_once()
        failing_voice.delete.assert_awaited_once()

    async def test_setup_hook_syncs_loaded_commands_to_event_guild(self):
        bot = OhioBot()
        try:
            load_extension = AsyncMock()
            sync = AsyncMock(return_value=[])
            with patch.object(bot, "load_extension", new=load_extension), patch.object(
                bot.tree, "clear_commands"
            ) as clear_commands, patch.object(
                bot.tree, "copy_global_to"
            ) as copy_global_to, patch.object(bot.tree, "sync", new=sync):
                await bot.setup_hook()

            self.assertEqual(load_extension.await_count, len(EXTENSIONS))
            guild = clear_commands.call_args.kwargs["guild"]
            clear_commands.assert_called_once_with(guild=guild)
            copy_global_to.assert_called_once_with(guild=guild)
            sync.assert_awaited_once_with(guild=guild)
            self.assertEqual(guild.id, config.discord_guild_id)
        finally:
            await bot.close()

    async def test_safe_error_response_uses_initial_response_or_followup(self):
        bot = OhioBot()
        try:
            initial = make_interaction(make_member(101))
            await bot._send_safe_error_response(initial)
            initial.response.send_message.assert_awaited_once_with(
                content="Something went wrong while processing that command.", ephemeral=True
            )
            initial.followup.send.assert_not_awaited()

            followup = make_interaction(make_member(101), response_done=True)
            await bot._send_safe_error_response(followup)
            followup.followup.send.assert_awaited_once_with(
                content="Something went wrong while processing that command.", ephemeral=True
            )
            followup.response.send_message.assert_not_awaited()
        finally:
            await bot.close()

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
            await verification_callback(self.verification_cog, interaction, "123456")
        self.assertIn(
            "not valid or has expired",
            interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(interaction)

        records.add_code("person@example.com", 202, "654321", 600)
        wrong_owner = make_interaction(user)
        await verification_callback(self.verification_cog, wrong_owner, "654321")
        self.assertIn(
            "not associated",
            wrong_owner.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(wrong_owner)

    async def test_verify_terminal_paths_edit_original_response(self):
        self.add_verified(101, email="verified@example.com")
        already_verified = make_interaction(make_member(101))
        await verification_callback(
            self.verification_cog, already_verified, "ignored"
        )
        self.assertIn(
            "already verified",
            already_verified.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(already_verified)

        unregistered = make_interaction(make_member(102))
        await verification_callback(
            self.verification_cog, unregistered, "missing@example.com"
        )
        self.assertIn(
            "no user's registered",
            unregistered.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(unregistered)

        self.add_verified(103, email="taken@example.com")
        already_used = make_interaction(make_member(104))
        await verification_callback(
            self.verification_cog, already_used, "taken@example.com"
        )
        self.assertIn(
            "already verified",
            already_used.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(already_used)

        records.add_registration(
            "sent@example.com", "Sent", "User", False, ["participant"]
        )
        sent = make_interaction(make_member(105))
        with patch.object(
            verification, "send_verification_email", new=AsyncMock(return_value=True)
        ):
            await verification_callback(self.verification_cog, sent, "sent@example.com")
        self.assertIn(
            "Check your inbox",
            sent.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(sent)

        records.add_registration(
            "failed@example.com", "Failed", "User", False, ["participant"]
        )
        failed = make_interaction(make_member(106))
        with patch.object(
            verification, "send_verification_email", new=AsyncMock(return_value=False)
        ):
            await verification_callback(
                self.verification_cog, failed, "failed@example.com"
            )
        self.assertIn(
            "Failed to send",
            failed.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(failed)

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

        with patch.object(verification, "sync_user_roles", new=AsyncMock()) as sync_roles:
            await verification_callback(self.verification_cog, interaction, "123456")

        self.assertTrue(records.is_verified(101))
        self.assertFalse(records.code_exists("123456"))
        sync_roles.assert_awaited_once_with(user)
        self.assertIn(
            "Welcome Pat",
            interaction.edit_original_response.call_args.kwargs["content"],
        )
        self.assert_deferred_response(interaction)

    async def test_verification_email_does_not_block_event_loop(self):
        self.add_verified(101, email="person@example.com")
        release_smtp = threading.Event()
        order = []

        class BlockingSMTP:
            def __enter__(self):
                order.append("smtp_started")
                release_smtp.wait(0.2)
                order.append("smtp_finished")
                return self

            def __exit__(self, *args):
                return None

            def login(self, *args):
                pass

            def sendmail(self, *args):
                pass

        async def unrelated_work():
            await asyncio.sleep(0)
            order.append("unrelated_work")
            release_smtp.set()

        with patch.object(verification.smtplib, "SMTP_SSL", return_value=BlockingSMTP()):
            sent, _ = await asyncio.gather(
                verification.send_verification_email(
                    "person@example.com", "123456", "person#0001"
                ),
                unrelated_work(),
            )

        self.assertTrue(sent)
        self.assertLess(order.index("unrelated_work"), order.index("smtp_finished"))

    async def test_verification_email_failure_is_safe(self):
        self.add_verified(101, email="person@example.com")
        with patch.object(
            verification.smtplib, "SMTP_SSL", side_effect=OSError("smtp unavailable")
        ):
            self.assertFalse(
                await verification.send_verification_email(
                    "person@example.com", "123456", "person#0001"
                )
            )
