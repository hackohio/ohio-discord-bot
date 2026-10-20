import discord
from discord.ext import commands
from discord import app_commands
from discord_bot.common import create_embed

from records import stats

class Stat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_notification_at: dict[int, float] = {}
    
    @app_commands.command(
        name="stats",
        description="Displays team count, lfg count, and participant count",
    )
  
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        [team_count, prtcpnt_count, lfg_count] = stats()
        embed=create_embed(
            title="Server Statistics", description="Here are some statistics for the server:"
        )   
        embed.add_field(name = "Total Teams: ", value = team_count)
        embed.add_field(name = "Verified Participants: ", value = prtcpnt_count)
        embed.add_field(name = "Participants looking for a group: ", value = lfg_count)
        await interaction.edit_original_response(embed = embed)

  
async def setup(bot: commands.Bot):
    await bot.add_cog(Stat(bot))