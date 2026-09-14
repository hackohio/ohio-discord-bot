"""Looking-for-group commands."""

import discord
from discord import app_commands
from discord.ext import commands

import records
from discord_bot.common import create_embed


class LfgCog(commands.Cog):
    lfg = app_commands.Group(
        name="lfg",
        description="Find teammates when you're looking for a group",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @lfg.command(
        name="toggle",
        description="Toggle whether you're looking for a team (optionally list your skills)",
    )
    @app_commands.describe(
        skills="Optional: skills/interests to show others (e.g. 'React, Python, UI design')"
    )
    async def lfg_toggle(
        self,
        interaction: discord.Interaction,
        skills: app_commands.Range[str, None, 150] | None = None,
    ):
        """Toggle the user's listing in the looking-for-group pool."""
        user = interaction.user
        await interaction.response.defer(ephemeral=True)

        if not records.is_verified(user.id):
            await interaction.edit_original_response(
                content="You need to verify first! Use the `/verify` command, then try again."
            )
            return

        if not records.get_verified_user(user.id)["is_participant"]:
            await interaction.edit_original_response(
                content="You must be a participant to look for a group!"
            )
            return

        already_looking = records.is_looking(user.id)

        if already_looking and not skills:
            records.remove_from_lfg(user.id)
            await interaction.edit_original_response(
                content="You're no longer marked as **looking for a team**. Run `/lfg toggle` again whenever you want to turn it back on."
            )
            return

        if already_looking and skills:
            records.add_to_lfg(user.id, skills)
            await interaction.edit_original_response(
                content=f"Updated your skills to: **{skills}**\nYou're still marked as **looking for a team**."
            )
            return

        if records.get_user_team_id(user.id):
            await interaction.edit_original_response(
                content="You're already on a team, so there's no need to look for one. Use `/leave_team` first if you want to find a different group."
            )
            return

        records.add_to_lfg(user.id, skills)
        message = "You're now marked as **looking for a team**! Others can find you with `/lfg view`."
        if not skills:
            message += "\n_Tip: run `/lfg toggle` again with the `skills` option to tell teams what you bring._"
        await interaction.edit_original_response(content=message)

    @lfg.command(name="view", description="See who's currently looking for a team")
    async def lfg_view(self, interaction: discord.Interaction):
        """Show the current looking-for-group pool."""
        await interaction.response.defer(ephemeral=True)

        seekers = records.get_lfg_list()
        present = []
        for seeker in seekers:
            member = interaction.guild.get_member(seeker["discord_id"])
            if member is not None:
                present.append((seeker, member))

        if not present:
            await interaction.edit_original_response(
                embed=create_embed(
                    "Looking for a Team",
                    "No one is currently looking for a team. Check back later, or mark yourself with `/lfg toggle`!",
                )
            )
            return

        lines = []
        shown = 0
        length = 0
        for seeker, member in present:
            name = seeker["first_name"] or seeker["username"]
            skills = seeker["skills"] if seeker["skills"] else "_No skills listed_"
            entry = f"**{name}** - {member.mention}\n> {skills}"
            if length + len(entry) + 2 > 3800:
                break
            lines.append(entry)
            length += len(entry) + 2
            shown += 1

        description = "\n\n".join(lines)
        remaining = len(present) - shown
        if remaining > 0:
            description += (
                f"\n\n_...and {remaining} more looking. The list will shrink as teams form._"
            )

        embed = create_embed(f"Looking for a Team ({len(present)})", description)
        await interaction.edit_original_response(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LfgCog(bot))
