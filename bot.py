import records
import config

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import smtplib
from email.mime.text import MIMEText

from typing import cast


# Init Bot Settings
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------Constants----------------------

MAX_TEAM_SIZE = 4
TEAM_FORMATION_TIMEOUT = 120

# Maps role names to corresponding role IDs from configuration
role_map = {
    "participant": config.discord_participant_role_id,
    "mentor": config.discord_mentor_role_id,
    "judge": config.discord_judge_role_id,
    "verified": config.discord_verified_role_id,
    "all-access": config.discord_all_access_pass_role_id,
}

# --------------------Helper Methods-------------------


def generate_random_code(n):  # TESTED
    """
    Generates random string of specified length using uppercase letters, lowercase letters, and digits.

    Args:
        length (int): the length of random string to generate

    Requires:
        length (int) >= 0

    Returns:
        str: A random string of specified length, containing digits.
    """
    characters = "0123456789"
    return "".join(random.choices(characters, k=n))


async def sync_user_roles(member: discord.Member):  # TESTED
    """
    Full Sync:
    1. Looks at every role defined in role_map.
    2. Adds it if the DB says they should have it.
    3. Removes it if the DB says they shouldn't (and they currently do).
    """

    # Check that memeber is verified and capable of having roles assinged
    if not records.is_verified(member.id):
        return

    # Get the list of roles the user SHOULD have from the DB
    email = records.get_verified_email(member.id)
    should_have_names = records.get_user_roles(email)
    should_have_names.append("verified")  # Always verified

    # All-Access-Pass if mentor or judge
    if "mentor" in should_have_names or "judge" in should_have_names:
        should_have_names.append("all-access")

    roles_to_add = []
    roles_to_remove = []

    # Iterate through the roles we manage (role_map)
    for role_name, role_id in role_map.items():

        discord_role = member.guild.get_role(role_id)
        if not discord_role:
            continue

        # Check if user has this role currently
        has_role = discord_role in member.roles

        # Check if they satisfy the requirement in the DB
        should_have = role_name in should_have_names

        # LOGIC:
        if should_have and not has_role:
            roles_to_add.append(discord_role)
        elif not should_have and has_role:
            roles_to_remove.append(discord_role)

    # 3. Apply Changes (Bulk operations are faster/safer)
    if roles_to_add:
        await member.add_roles(*roles_to_add)
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)


async def handle_team_deletion(team_id: int):  # TESTED
    """
    Handles the timeout of team formation when team doesn't meet minimum size requirement

    If team has fewer than two members when timeout, this function will:
        1. remove team assigned role from all current members of team.
        2. remove team association from members in database
        3. delete team associated channels
        4. sends message explaining timeout and team re-creation process

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        team_id (int): The unique ID of the team
    """
    guild = bot.get_guild(config.discord_guild_id)
    if records.team_exists(team_id):

        # Remove Role and team_id from each user on team
        for member in records.get_team_members(team_id):
            member_obj = guild.get_member(member["discord_id"]) if guild else None
            if member_obj:
                await perform_team_leave(member_obj, team_id)
            else:
                # TODO: Log that user couldn't be found on server?
                pass

        # Remove all Channels
        await delete_team_channels(team_id)
        records.remove_team(team_id)


async def send_verification_email(recipient, CODE, username):  # TESTED
    """
    Sends verification email to recipient with one-time use link for verifying Discord account

    Args:
        recipient (str): Email address of the users to send the verificatio link to.
        CODE (str): A randomly generated verification code used in verification link.
        username (str): The Discord username of the person requesting verification.

    Returns:
        bool: True if email was sent successfully, False if there was error.

    Raises:
        Exception: If there is an error with sending email, prints error message.

    """
    body = f"""Dear {records.get_first_name(recipient)},<br>
        To verify that your email is associated with the discord account: {username}, please enter the code below:<br><br>
        <h3>{CODE}</h3><br>
        If you didn’t attempt to verify your account, you can safely ignore this email.<br><br>
        This code will expire in {round(config.email_code_expiration_time/60)} minutes. If it has expired, please request a new verification email.<br><br>
        Thank you,<br>
        OHI/O Hackathon Team<br><br>
        If you have any issues or questions, please contact us at {config.contact_organizer_email} or message in the Ask an Organizer channel on discord
        """
    msg = MIMEText(body, "html")
    msg["Subject"] = "Verify your Discord Account"
    msg["From"] = config.email_address
    msg["To"] = recipient
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp_server:
            smtp_server.login(config.email_address, config.email_password)
            smtp_server.sendmail(config.email_address, recipient, msg.as_string())
        return True
    except Exception as e:
        print(f"ERROR: Message not to {recipient} not sent. ERROR: {e}")
        return False


async def delete_team_channels(team_id: int):  # TESTED
    """
    Deletes all channels and roles associated with a team.
    Args:
        team_id (int): The team ID of the team to delete channels for.
    """
    # Get all channels and role from database
    guild = bot.get_guild(config.discord_guild_id)
    team_data = records.get_team(team_id)

    category_id = team_data["category_id"]
    text_id = team_data["text_id"]
    voice_id = team_data["voice_id"]
    role_id = team_data["role_id"]

    if guild:
        category = guild.get_channel(category_id) if category_id else None
        text = guild.get_channel(text_id) if text_id else None
        voice = guild.get_channel(voice_id) if voice_id else None
        role = guild.get_role(role_id) if role_id else None

        if text:
            await text.delete()
        if voice:
            await voice.delete()
        if role:
            await role.delete()
        if category and not config.discord_shared_categories:
            await category.delete()
    else:
        # TODO: Log that guild couldn't be found?
        pass


def can_join_team(added_member: discord.Member) -> int:  # TESTED
    """
    Checks if a user is able to join a team

    Args:
        added_member (discord.Member): Check if this user can join a team

    Returns:
        int: Status Code:
            -1: User is not verified
            -2: User is not a participant
            -3: User is already on a team
             0: User can join team
    """
    # Check that added_user is verified
    if not records.is_verified(added_member.id):
        return -1

    # Check if added_user is a participant
    email = records.get_verified_email(added_member.id)
    if not records.get_verified_user(email)["is_participant"]:
        return -2

    # Check if add_user is already on a team
    if records.get_user_team_id(added_member.id):
        return -3

    return 0


async def perform_team_join(member: discord.Member, team_id: int):  # TESTED
    # DB Update
    records.join_team(member.id, team_id)

    guild = bot.get_guild(config.discord_guild_id)
    team_data = records.get_team(team_id)

    if guild:
        # Get Roles to add
        roles_to_add = []
        if team_data and "role_id" in team_data:
            t_role = guild.get_role(team_data["role_id"])
            if t_role:
                roles_to_add.append(t_role)
        a_role = guild.get_role(config.discord_team_assigned_role_id)
        if a_role:
            roles_to_add.append(a_role)

        # Add Roles to Users
        if roles_to_add:
            await member.add_roles(*roles_to_add)
    else:
        # TODO: Log that guild couldn't be found?
        pass


async def perform_team_leave(member: discord.Member, team_id: int):  # TESTED

    guild = bot.get_guild(config.discord_guild_id)
    team_data = records.get_team(team_id)

    # Drop Team
    records.leave_team(member.id)

    if guild:
        # Get Roles to Remove
        roles_to_remove = []
        if team_data and "role_id" in team_data:
            t_role = guild.get_role(team_data["role_id"])
            if t_role:
                roles_to_remove.append(t_role)
        a_role = guild.get_role(config.discord_team_assigned_role_id)
        if a_role:
            roles_to_remove.append(a_role)

        # Remove Roles from User
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
    else:
        # TODO: Log that guild couldn't be found?
        pass


# -------------------"/" Command Methods-----------------------------


@bot.tree.command(name="affirm", description="Recieve a random affirmation for encouragement")
async def affirm(interaction: discord.Interaction):
    affirmations = {
        "You're doing amazing—every line of code is one step closer to something great!",
        "Remember, the best solutions often come from the toughest challenges. Keep going!",
        "You belong here. Your ideas matter and are worth sharing.",
        "It's not about having all the answers; it's about asking the right questions. You're doing great!",
        "Every bug you squash is a step closer to innovation. Keep debugging!",
        "Your creativity is your superpower. Let it shine!",
        "It's okay to take breaks. Rest fuels brilliance.",
        "You’re capable of more than you realize—trust the process.",
        "Collaboration is key, and you're an invaluable part of your team!",
        "Progress, not perfection, is the goal. You're moving forward, and that's what counts.",
        "Hackathons are marathons, not sprints. Pace yourself and enjoy the journey!",
        "Remember, even the greatest projects started with a single idea. Keep building!",
        "You’re not alone; your teammates and community are here to support you.",
        "Every keystroke is an act of creativity. You're a digital artist!",
        "Challenges are opportunities in disguise. Embrace them and thrive!",
        "Your dedication inspires others. Keep up the amazing work!",
        "Celebrate small victories—they lead to big successes!",
        "Think outside the box. Your unique perspective is your advantage!",
        "You're making something out of nothing—that's incredible!",
        "No matter the outcome, you're learning, growing, and creating. That's a win!",
    }
    random_affirm = random.choice(list(affirmations))
    await interaction.response.send_message(ephemeral=True, content=f"{random_affirm}")


@app_commands.guild_only()  # Makes sure no-one can verify over dm?
@bot.tree.command(name="verify", description="Verify your Discord account for this Event")
@app_commands.describe(email_or_code="Email Address used to Register / or / Verification Code")
async def verify(interaction: discord.Interaction, email_or_code: str):  # TESTED
    """
    Verifies a user's Discord account by linking it with their reg email

    This function:
    1. Checks if the email is registered
    2. Checks if user is already verified
    3. Checks if email is already associated with a verified account
    4. Associates the user's Discord ID with email if they are registered but not yet verified
    5. Sends a verification code via email and waits for user to confirm
    6. Removes expired verification codes after a specified timeout

    Args:
        ctxt (Context): The Context of the Interaction
        flags (emailFlag): Flag containing email address to be verified
    """
    user = interaction.user
    guild = bot.get_guild(config.discord_guild_id)
    user = guild.get_member(user.id) or await guild.fetch_member(user.id) if guild else None

    # Tell discord to wait before crashing session
    await interaction.response.defer(ephemeral=True)

    # Check if user is already verified
    if user:
        if records.is_verified(user.id):
            first_name = records.get_first_name(records.get_verified_email(user.id))
            await interaction.followup.send(
                content=f"Welcome, {first_name}! You are already verified."
            )
            return
    else:
        await interaction.followup.send(
            content="There was an error retrieving your Discord account information. Please contact an organizer for assistance."
        )
        return

    # Case 1: CODE was entered (Check Code)
    if email_or_code.isdigit():
        code = email_or_code

        # Check that code is valid
        if not records.code_exists(code):
            await interaction.followup.send(
                content="Your Verification Code is either not valid or has expired. Please request a new one."
            )
            return

        # Retrieve Message ID or Verification message
        code_info = records.get_value_from_code(code)

        # Check that user_id matches user entering the code
        if code_info["discord_id"] != user.id:
            await interaction.followup.send(
                content=f"The code you entered is not associated with your discord account. Please request a new one by entering the email you registered with."
            )
            return

        # ------------- Happy Case --------------------

        email = code_info["email"]

        # Add user to verified database
        records.add_verified_user(email, user.id, user.name)
        records.remove_code(code)

        # Assign user with all given roles
        await sync_user_roles(user)

        # Send the user a message that they have been verified and the next steps
        channel = guild.get_channel(config.discord_start_here_channel_id) if guild else None
        channel_mention = channel.mention if channel else "Start Here channel"
        await interaction.followup.send(
            content=f"Welcome {records.get_first_name(email)}! \nYou have been verified. Please check the {channel_mention} channel for next steps."
        )

    # Case 2: Email was entered
    else:
        email = email_or_code

        # Confirm user is registered
        if not records.is_registered(email):
            await interaction.followup.send(
                content=f"There are no user's registered with the email: `<{email}>`. \nPlease verify using the correct email, reregister at {config.contact_registration_link}, or contact administration."
            )
            return

        # Check if email is in verified DB
        if records.is_verified(email):
            await interaction.followup.send(
                content=f"A User with that email address is already verified. \nPlease reregister with a different email address at {config.contact_registration_link}"
            )
            return

        # ------------- Happy Case --------------------

        # NOTE: DB automatically replaces any code entry that matches discord_id, code, or email
        # Send Verification Info to web for update
        CODE = generate_random_code(6)
        while records.code_exists(CODE):
            CODE = generate_random_code(6)

        if await send_verification_email(email, CODE, user.name):
            records.add_code(email, user.id, CODE)
            await interaction.followup.send(
                content=f"Check your inbox for an email from `<{config.email_address}>` with a verification link. Please check that email and enter the code in this format \n `/verify (code)`\n Be sure to check your junk folder if you have trouble finding it"
            )
        else:
            await interaction.followup.send(
                content="Failed to send verification email. Please contact an organizer for assistance."
            )

        # Wait for timeout then delete verification code
        await asyncio.sleep(config.email_code_expiration_time)
        records.remove_code(CODE)


@app_commands.guild_only()
@bot.tree.command(name="create_team", description="Create a new team for this event")
@app_commands.describe(team_name="Name/Label for your Team")
async def create_team(
    interaction: discord.Interaction,
    team_name: str,
    teammate_1: discord.Member,
    teammate_2: discord.Member | None = None,
    teammate_3: discord.Member | None = None,
):
    """
    Creates a new team, assigning user to team and creating necessary roles and channels

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (teamNameFlag): The flags passed containing the team name and teammates users.

    Requires:
        - cannot already be in team
        - user has to be verified and participant

        teamname: str = commands.flag(description = "Name of your team")
        teammate1: discord.Member = commands.flag(description="Username of Teammate")
        teammate2: discord.Member = None
        teammate3: discord.Member = None
    """

    # Retrieve Context
    user = interaction.user
    guild = interaction.guild
    user = guild.get_member(user.id) or await guild.fetch_member(user.id) if guild else None

    await interaction.response.defer(ephemeral=True)

    # ------------- Check if Team and Creator is Valid --------------------
    if user:
        author_status = can_join_team(user)
        match author_status:
            case -1:
                await interaction.followup.send(
                    content="You are not verified! Please verify yourself with the /verify command"
                )
                return
            case -2:
                await interaction.followup.send(
                    content="You are not a participant. You cannot create a team"
                )
                return
            case -3:
                await interaction.followup.send(
                    content="You are already on a team. You can leave with the /leave_team command"
                )
                return
    else:
        await interaction.followup.send(
            content="There was an error retrieving your Discord account information. Please contact an organizer for assistance."
        )
        return

    # Check that team doesn't already exist
    if records.team_exists(team_name):
        await interaction.followup.send(
            content="That team name is already in use. Please chose a different name"
        )
        return

    # -------------- Check if Members added are Valid -------------------

    # Check that atleast one member can be added to team
    members = [teammate_1, teammate_2, teammate_3]
    valid_members = []
    for mem in members:
        if not mem:
            continue
        match can_join_team(mem):
            case -1 | -2:
                await interaction.followup.send(
                    ephemeral=True,
                    content=f"Failed to add team member. {mem.mention} is not a verified participant.",
                )
            case -3:
                await interaction.followup.send(
                    ephemeral=True,
                    content=f"Failed to add team member. {mem.mention} is already on a team. To join, they must leave using /leaveteam",
                )
            case 0:
                valid_members.append(mem)

    if not valid_members:
        await interaction.followup.send(
            ephemeral=True,
            content=f"Team creation failed - No teammates could be added. \nChoose a different teammate or reach out to them to fix their problem.",
        )
        return

    # -------------------- Create Team Channels -------------------------

    if guild:
        team_role = await guild.create_role(name=team_name)

        category_channel_perms = {
            guild.get_role(config.discord_all_access_pass_role_id): discord.PermissionOverwrite(
                view_channel=True
            ),
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            team_role: discord.PermissionOverwrite(view_channel=True),
        }
        text_channel_perms = {
            guild.get_role(config.discord_all_access_pass_role_id): discord.PermissionOverwrite(
                view_channel=True
            ),
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            team_role: discord.PermissionOverwrite(view_channel=True),
        }
        voice_channel_perms = {
            team_role: discord.PermissionOverwrite(connect=True, view_channel=True, speak=True),
            guild.get_role(config.discord_all_access_pass_role_id): discord.PermissionOverwrite(
                connect=True, view_channel=True, speak=True
            ),
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
    else:
        await interaction.followup.send(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance."
        )
        return

    next_team_id = records.get_next_team_id()
    category_channel = None
    text_channel = None
    voice_channel = None

    # TODO: Add Table for Category channels for shared_categories

    if guild:
        # Case 1: Each team has their own category and voice channel
        if not config.discord_shared_categories:

            category_channel = await guild.create_category_channel(
                f"Team {next_team_id} - {team_name}", overwrites=category_channel_perms
            )
            text_channel = await category_channel.create_text_channel(
                f"{team_name.replace(' ','-')}-text", overwrites=text_channel_perms
            )
            voice_channel = await category_channel.create_voice_channel(
                f"{team_name.replace(' ','-')}-voice", overwrites=voice_channel_perms
            )

        # Case 2: Categories hold text-channels 1-50, etc
        else:

            channels_per_category = 50
            new_channel_needed = (
                (next_team_id - 1) % channels_per_category == 0
            ) or not records.get_latest_category()

            if new_channel_needed:  # New category channel needs made
                category_channel = await guild.create_category_channel(
                    f"Teams {next_team_id} - {(next_team_id - 1) + channels_per_category}",
                    overwrites=category_channel_perms,
                )
                records.push_new_category(category_channel.id)

            else:  # Use a previous team's category channel
                category_channel = cast(
                    discord.CategoryChannel, bot.get_channel(records.get_latest_category())
                )

            text_channel = await category_channel.create_text_channel(
                f"{next_team_id}-{team_name.replace(' ','-')}-text",
                overwrites=text_channel_perms,
            )  # Inherit perms from Category

        # ----------------------- Create Team ------------------------

        team_id = records.create_team(
            team_name,
            team_role.id,
            category_channel.id,
            text_channel.id,
            voice_channel.id if voice_channel else None,
        )

        # Let user know that team was succesfully created
        await interaction.followup.send(
            content=f"Your Team ({team_role.mention}) has successfully been created!. \nManage your team using the `/add_member` and `/remove_member` commands"
        )

        # Add Author and Valid Teammates to team
        await perform_team_join(user, team_id)  # Add author to team
        records.set_team_lead(team_id, user.id)  # Make author team_lead
        for mem in valid_members:
            await perform_team_join(mem, team_id)
            await interaction.followup.send(
                ephemeral=True,
                content=f"Team member added successfully. {mem.mention} has been added to {team_role.mention}.",
            )
            await text_channel.send(
                content=f"{mem.mention} has been added to the team by {interaction.user.mention}."
            )
    else:
        await interaction.followup.send(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance."
        )
        return


@app_commands.guild_only()
@bot.tree.command(name="leave_team", description="Leave your current team")
async def leave_team(interaction: discord.Interaction):  # TESTED
    """
    Command for a user to leave their current team.
    The user will:
        - be removed from the team
        - have team roles removed

    Team channel will be notified of departure. If not members are left, the team will be fully deleted.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
    """

    user = interaction.user
    guild = bot.get_guild(config.discord_guild_id)
    user = guild.get_member(user.id) or await guild.fetch_member(user.id) if guild else None

    await interaction.response.defer(ephemeral=True)

    # ------------- Do Validation Checks --------------------

    # Ensure user is on a team
    if user:
        if not records.get_user_team_id(user.id):
            await interaction.followup.send(
                content="You cannot leave a team since you are not assigned to one!"
            )
            return
    else:
        await interaction.followup.send(
            content="There was an error retrieving your Discord account information. Please contact an organizer for assistance."
        )
        return

    # ------------- Happy Case --------------------

    # Grab Team Relavent Info
    if guild:
        team_id = records.get_user_team_id(user.id)
        team_data = records.get_team(team_id)
        team_text_channel: discord.TextChannel = cast(
            discord.TextChannel, guild.get_channel(team_data["text_id"])
        )
        team_role = guild.get_role(team_data["role_id"])
    else:
        await interaction.followup.send(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance."
        )
        return

    # Remove user from team
    team_role_mention = team_role.mention if team_role else ""
    await perform_team_leave(user, team_id)
    await interaction.followup.send(
        content=f"You have successfully been removed from the team {team_role_mention}."
    )

    # Delete team if no one is left
    if records.get_team_size(team_id) == 0:
        await handle_team_deletion(team_id)
        return

    # If they were team lead, replace team_lead
    team_lead_id = team_data["team_lead"]
    if team_lead_id == user.id:

        # Chose a random other teammate to assign as lead
        new_lead_id = random.choice(records.get_team_members(team_id))["discord_id"]
        records.set_team_lead(team_id, new_lead_id)

        new_lead_member = guild.get_member(new_lead_id) if guild else None
        new_lead_mention = new_lead_member.mention if new_lead_member else ""

        await team_text_channel.send(
            content=f"{user.mention} has left the team.\n{new_lead_mention} has been randomly assigned as the new Team Lead."
        )

    else:
        await team_text_channel.send(content=f"{user.mention} has left the team.")


@app_commands.guild_only()
@bot.tree.command(name="add_member", description="Add a member to your team")
@app_commands.describe(member="The member to add to your team")
async def add_member(interaction: discord.Interaction, member: discord.Member):  # TESTED
    """
    Adds a specified member to the team of the user who invokes the command.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (userFlag): The user specified in the command input.
    """

    guild = interaction.guild
    if not guild:
        await interaction.response.send_message(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
            ephemeral=True,
        )
        return

    team_user = interaction.user  # User who invoked the command
    added_user = member  # The user to be added to the taem
    await interaction.response.defer(ephemeral=True)

    # ------------- Do Validation Checks --------------------

    # Check that team_user is in a team
    if not records.get_user_team_id(team_user.id):
        await interaction.followup.send(
            content="Failed to add team member. You are not currently in a team. You must be in a team to add a team member. Please use `/create_team` to create a team or have another participant use `/add_member` to add you to their team"
        )
        return

    # Check if member is already on your team
    if records.get_user_team_id(team_user.id) == records.get_user_team_id(member.id):
        await interaction.followup.send(
            content=f"Failed to add team member. {member.mention} is already on your team!"
        )
        return

    # Check that team is not full
    team_id = records.get_user_team_id(team_user.id)
    if records.get_team_size(team_id) >= MAX_TEAM_SIZE:
        await interaction.followup.send(
            content=f"Failed to add team member. There is no space in your team. Teams can have a maximum of {MAX_TEAM_SIZE} members."
        )
        return

    # Check if user can join the team
    match can_join_team(added_user):
        case -1 | -2:
            await interaction.followup.send(
                content=f"Failed to add team member. {added_user.mention} is not a verified participant."
            )
            return
        case -3:
            await interaction.followup.send(
                content=f"Failed to add team member. {added_user.mention} is already on a team. To join, they must leave using /leave_team"
            )
            return

    # ------------- Happy Case --------------------

    # Add the member to the team
    await perform_team_join(added_user, team_id)

    team_data = records.get_team(team_id)
    team_role = guild.get_role(team_data["role_id"])
    if not team_role:
        await interaction.followup.send(
            content="There was an error retrieving your team's role information. Please contact an organizer for assistance."
        )
        return

    text_channel = cast(discord.TextChannel, guild.get_channel(team_data["text_id"]))
    if not text_channel:
        await interaction.followup.send(
            content="There was an error retrieving your team's text channel information. Please contact an organizer for assistance."
        )
        return

    # Send confirmation message to team_user
    await interaction.followup.send(
        content=f"Team member added successfully. {added_user.mention} has been added to {team_role.mention}."
    )

    # Notify team in team text channel of new member
    await text_channel.send(
        content=f"{added_user.mention} has been added to the team by {team_user.mention}."
    )


@app_commands.guild_only()
@bot.tree.command(
    name="remove_member", description="Remove a member from your team (Team Lead Only)"
)
@app_commands.describe(member="The member to remove from your team")
async def remove_member(interaction: discord.Interaction, member: discord.Member):  # TESTED
    """
    Removes a specific member from the team of the user who invokes the command.
    User must be a "team_lead" to invoke (Created the team)
    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (userFlag): The user specified in the command input.
    """

    guild = interaction.guild
    if not guild:
        await interaction.response.send_message(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
            ephemeral=True,
        )
        return

    team_user = interaction.user  # User who invoked the command
    await interaction.response.defer(ephemeral=True)

    # ------------- Do Validation Checks --------------------

    # Check that team_user is in a team
    if not records.get_user_team_id(team_user.id):
        await interaction.followup.send(
            content="Failed to remove team member. You are not currently in a team."
        )
        return

    # Check that user is the team_lead
    team_id = records.get_user_team_id(team_user.id)
    team_lead_id = records.get_team(team_id)["team_lead"]

    if team_lead_id != team_user.id:
        team_lead_member_obj = guild.get_member(team_lead_id)
        team_lead_mention = (
            f"{team_lead_member_obj.mention} is your lead." if team_lead_member_obj else ""
        )
        await interaction.followup.send(
            content=f"Only the Team Lead can invoke this command!\n{team_lead_mention} Contact them for to invoke the command"
        )
        return

    # Check if member is on your team
    if records.get_user_team_id(team_user.id) != records.get_user_team_id(member.id):
        await interaction.followup.send(
            content=f"Failed to remove team member. {member.mention} is not on your team!"
        )
        return

    # ------------- Happy Case --------------------

    # Add the member to the team
    await perform_team_leave(member, team_id)

    team_data = records.get_team(team_id)
    text_channel: discord.TextChannel = cast(
        discord.TextChannel, guild.get_channel(team_data["text_id"])
    )

    # Send confirmation message to team_user
    await interaction.followup.send(content=f"{member.mention} has been removed successfully.")

    # Notify team in team text channel of new member
    await text_channel.send(
        content=f"{member.mention} has been removed from the team by {team_user.mention}."
    )

    # Notify removed member over dm
    await member.send(
        content=f"You have been removed from the team <{team_data['name']}>. \nYou can join a new team or create your own using `/create_team`"
    )


# ------------------- Admin Only Commands ----------------------


@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@bot.tree.command(
    name="overify",
    description="Manually verify a Discord account for this event (Organizers only)",
)
@app_commands.describe(role="User Role: 'participant', 'mentor', or 'judge'")
async def overify(
    interaction: discord.Interaction,
    member_to_promote: discord.Member,
    email_address: str,
    first_name: str,
    last_name: str,
    is_capstone: bool,
    role: str,
):  # TESTED
    """
    Manually verifies a Discord account for the event, allowing organizers to assign roles and verify users.

    If the user doesn't exist, add them to the database and assign roles.
    If the user exists, update role and updata database.
    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (registerFlag): Flag that contains registrant information (user, email, and role)

    Requires:
        User is an admin
    """

    await interaction.response.defer(ephemeral=True)

    # Check if role is valid to be overified with
    if not (role in role_map):
        await interaction.followup.send(
            content=f"`<{role}>` is not a valid role. \nPlease chose either `participant`, `mentor`, or `judge`"
        )
        return

    # Case 1: User is already verified (Add Role)
    if records.is_verified(member_to_promote.id):
        verified_email = records.get_verified_email(member_to_promote.id)

        # Check if user has role specified, else add it
        if role in records.get_user_roles(verified_email):
            await interaction.followup.send(
                content=f"`<{member_to_promote.name}>` is verified and already has the role `<{role}>`."
            )
            return

        # Update user in database
        roles = records.get_user_roles(verified_email)
        if not (role in roles):
            roles.append(role)
            records.update_roles(verified_email, roles)

        await interaction.followup.send(
            content=f"`<{member_to_promote.name}>` is already verified but has been given the role `<{role}>`."
        )

    # Case 2: User is not Verified (Register and Verify User with the appropriate roles)
    else:
        records.add_registration(email_address, first_name, last_name, is_capstone, [role])
        records.add_verified_user(email_address, member_to_promote.id, member_to_promote.name)
        await interaction.followup.send(
            content=f"`<{member_to_promote.name}>` has been verified and given the role `<{role}>`."
        )

    # Assign the overified user any roles assigned
    await sync_user_roles(member_to_promote)


@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="delete_team", description="Remove Team (Organizers only)")
async def delete_team(
    interaction: discord.Interaction, team_role: discord.Role, reason_for_removal: str
):  # TESTED
    """
    Delete a team and its associated data from the event.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction
        flags (removeTeamFlag): Flags containing the 'team_role' and 'reason' for removal
    """

    guild = interaction.guild
    if not guild:
        await interaction.response.send_message(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    # Retrieve team details before removal
    team_name = team_role.name
    team_id = records.get_team(team_name)["id"]
    members = records.get_team_members(team_name)

    # ------------- Happy Case --------------------

    # Notify team and admin about removal
    for member in members:
        member_obj = guild.get_member(member["discord_id"])
        (
            await member_obj.send(
                content=f"Your team has been removed from the event. \nReason: `{reason_for_removal}`. \nYou may create a new team but continued failure to comply may result in being permanently removed"
            )
            if member_obj
            else None
        )

    await interaction.followup.send(
        content=f"The team `<{team_name}>` has been removed and the members have been notified"
    )

    # Remove channels and remove team stats from members
    await handle_team_deletion(team_id)


@bot.tree.command(name="broadcast", description="Broadcast a message to each team channel")
@app_commands.default_permissions(administrator=True)
async def broadcast(interaction: discord.Interaction, message: str):
    """
    Broadcasts a message to each team's text channel.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (messageFlag): Flag containing the message to broadcast.
    """

    guild = interaction.guild
    if not guild:
        await interaction.response.send_message(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)

    teams = records.get_all_teams()
    print(teams)
    for team in teams:
        team_text_channel = cast(discord.TextChannel, guild.get_channel(team.get("text_id")))
        role_obj = guild.get_role(team.get("role_id"))
        if not role_obj:
            continue
        team_mention = role_obj.mention
        if team_text_channel:
            await team_text_channel.send(content=f"{team_mention}\n{message}")

    await interaction.followup.send(
        content="Broadcast message sent to all team channels.", ephemeral=True
    )


@bot.tree.command(name="broadcast", description="Broadcast a message to each team channel")
@app_commands.default_permissions(administrator=True)
async def broadcast(interaction: discord.Interaction, message: str):
    """
    Broadcasts a message to each team's text channel.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (messageFlag): Flag containing the message to broadcast.
    """

    guild = interaction.guild
    if not guild:
        await interaction.response.send_message(
            content="There was an error retrieving the Discord server information. Please contact an organizer for assistance.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)

    teams = records.get_all_teams()
    print(teams)
    for team in teams:
        team_text_channel = cast(discord.TextChannel, guild.get_channel(team.get("text_id")))
        role_obj = guild.get_role(team.get("role_id"))
        if not role_obj:
            continue
        team_mention = role_obj.mention
        if team_text_channel:
            await team_text_channel.send(content=f"{team_mention}\n{message}")

    await interaction.followup.send(
        content="Broadcast message sent to all team channels.", ephemeral=True
    )


@bot.hybrid_command(name="sync", description="Sync commands (Organizer Only)")
@app_commands.default_permissions(administrator=True)
@commands.has_permissions(administrator=True)
@app_commands.describe(spec="Scope of the sync (Local, Global, or Clear)")
async def sync(ctx: commands.Context, spec: str):
    """
    Syncs the bot commands.
    Usage:
    /sync [spec]
      - local    : Copy global commands to current server (Instant Dev)
      - global   : Sync globally (Takes 1 hour)
      - clear    : Wipe local commands
    """

    guild = ctx.guild
    if not guild:
        await ctx.send("There was an error retrieving the Discord server information.")
        return

    await ctx.defer(ephemeral=True)

    if spec.lower() == "local":
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)

        await ctx.send(
            f"✅ **Local Sync:** Copied and synced {len(synced)} commands to this server."
        )
        return

    if spec.lower() == "global":
        synced = await bot.tree.sync()
        await ctx.send(
            f"🌎 **Global Sync:** Synced {len(synced)} commands globally. (Updates may take up to 1 hour)."
        )
        return

    if spec.lower() == "clear":
        bot.tree.clear_commands(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)
        await ctx.send("🧹 Cleared guild-specific commands.")
        return

    await ctx.send("Please provide a valid spec argument (local, global, clear)")


# When the bot is ready, this automatically runs
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


def start():
    bot.run(config.discord_token)


# ------------------------------------------------------------------

# TODO: Allow 5 people to join a team if they are capstone
# TODO: Rewrite web.py with new db material and same with export/import
