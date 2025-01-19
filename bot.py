import os
import records
import config
import web

import discord
from discord.ext import commands
import asyncio
import random
import smtplib
from email.mime.text import MIMEText

"""
Valid Roles:
    - participant
    - mentor
    - judge
    - organizer
"""

#Init Bot Settings
intents = discord.Intents.all()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='/', intents=intents)

#---------------------Constants----------------------

MAX_TEAM_SIZE = 4
TEAM_FORMATION_TIMEOUT = 120

# Maps role names to corresponding role IDs from configuration
role_map = {
    "participant": config.discord_participant_role_id,
    "mentor": config.discord_mentor_role_id,
    "judge": config.discord_judge_role_id,
    # "organizer": config.discord_organizer_role_id, # Removed for Security Purposes
    "verified": config.discord_verified_role_id
}

# --------------------Helper Methods-------------------
async def assign_user_roles(user, roles: list): #TESTED 
    """
    Assigns specified roles to the user based on provided role names.

    Args:
        user (discord.Member): The Discord user to whom the roles will be assigned.
        roles (list): A list of role names (e.g., "participant", "mentor", "judge") that the user should be assigned
    """
    
    for role_name in roles:
        if role_name in role_map:
            role = discord.utils.get(user.guild.roles, id=role_map[role_name])
            if role:
                await user.add_roles(role)
            else:
                print(f"Role '{role_name}' not found in the server.")
        else:
            print(f"Invalid role name '{role_name}' provided.")

async def remove_roles(user: discord.Member, roles:list): #TESTED 
    """
    Removes specified roles from a Discord user.

    Args:
        user (discord.Member): The Discord user whose roles will be modified.
        roles (list): A list of roles that should be removed from the user.
    """
    roles_set = set(roles)
    old_roles = user.roles
    new_roles = []

    # If role is not contained in the set of roles to remove
    for role in old_roles:
        if role not in roles_set:
            new_roles.append(role)

    # Update user with new roles
    await user.edit(roles=new_roles)

def generate_random_code(n): #TESTED
    """
    Generates random string of specified length using uppercase letters, lowercase letters, and digits.

    Args:
        length (int): the length of random string to generate

    Requires:
        length (int) >= 0
        
    Returns:
        str: A random string of specified length, containing digits.
    """
    characters = '0123456789'
    return ''.join(random.choices(characters, k=n))    


async def handle_team_formation_timeout(ctxt: discord.Interaction, team_id: int): #TESTED 
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
    if records.team_exists(team_id) and records.get_team_size(team_id) <= 1:
        # Remove Role and team_id from each user on team
        for member in records.get_team_members(team_id):
            await remove_roles(ctxt.guild.get_member(member[0]), [ctxt.guild.get_role(config.discord_team_assigned_role_id)])
            records.drop_team(member[0])
            
        # Remove all Channels
        await delete_team_channels(team_id)
        await ctxt.send(ephemeral=True,
                        content=f'Team formation timed out. Teams must have at least two members {round(TEAM_FORMATION_TIMEOUT/60)} minutes after creation to be saved. You must re-create your team and use the `/addmember` command to add members to your team within one minute of using the `/createteam` command.')

async def send_verification_email(recipient, CODE, username): #TESTED 
    """
    Sends verification email to recipientwith one-time use link for verifying Discord account
    
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
    msg = MIMEText(body, 'html')
    msg['Subject'] = 'Verify your Discord Account'
    msg['From'] = config.email_address
    msg['To'] = recipient
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(config.email_address, config.email_password)
            smtp_server.sendmail(config.email_address, recipient, msg.as_string())

        return True
    except Exception as e:
        print(f"ERROR: Message not to {recipient} not sent. ERROR: {e}")
        return False

async def delete_team_channels(team_id: int): #TESTED 
    """
    Deletes all channels and role associateed with a team, and removes the team from database

    Args:
        team_id (int): The unique ID of the team to delete.
        
    Requires:
        team_id exists and associated with a team
    """
    # Get all channels from database
    guild = bot.get_guild(config.discord_guild_id)
    channels = records.get_team(team_id)['channels']

    #Delete all channels and role
    for channel in channels:
        if(channel == 'role'):
            await guild.get_role(channels[channel]).delete()
        else:
            await guild.get_channel(channels[channel]).delete()

    # Remove team from database
    records.remove_team(team_id)

async def handle_permission_error(ctxt: discord.Interaction, error: discord.errors): #TESTED 
    await ctxt.send(ephemeral=True,
                               content='You do not have permission to use this command.')

# ---------------------Classes-------------------------

#Retrieves Member username (Can be used for adding members)
class userFlag(commands.FlagConverter):
    member: discord.Member = commands.flag(description='The User being selected')

#Retrieves Email
class verifyFlag(commands.FlagConverter):
    email_or_code: str = commands.flag(description = 'Email Address used to Register / or / Verification Code')

#Retrieves Team Name
class teamNameFlag(commands.FlagConverter):
    teamname: str = commands.flag(description = "Name of your team")

#Details to register user to database
class registerFlag(commands.FlagConverter):
    member: discord.Member = commands.flag(description="Discord User")
    email: str = commands.flag(description="User Email Address")
    role: str = commands.flag(description="User Role: 'participant', 'mentor', or 'judge'")

class removeTeamFlag(commands.FlagConverter):
    team_role: discord.Role = commands.flag(description="Team to Remove")
    reason: str = commands.flag(description="Reason for Removal")
#-------------------"/" Command Methods-----------------------------

#Test Greet Command - Anyone can run
@bot.tree.command(description="Recieve a random affirmation for encouragement") # TESTED
async def affirm(ctxt):
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
        "No matter the outcome, you're learning, growing, and creating. That's a win!"
    }
    random_affirm = random.choice(list(affirmations))
    await ctxt.response.send_message(ephemeral=True, content=f'{random_affirm}')

# ----------- Email/Account Verification ----------------------------------------------
@bot.hybrid_command(description="Verify your Discord account for this Event") # TESTED
async def verify(ctxt, flags: verifyFlag):
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
    
    user = ctxt.author
    email = flags.email_or_code

    # ------------------ Handle if a code is entered (all digits) --------------------------------
    if (email.isdigit()):
        code = email

        # Check that code is valid
        if not records.code_exists(code):
            await ctxt.send(ephemeral=True,
                            content="Your Verification Code is either not valid or has expired. Please request a new one.")
            return
            
        # Retrieve Message ID or Verification message
        user_id = records.get_value_from_code(code)

        # Check that user_id matches user entering the code
        if user_id != user.id:
            await ctxt.send(ephemeral=True,
                            content=f"The code you entered is not associated with your discord account. Please request a new one by entering the email you registered with.")
            return

        """ Happy Case """

        email = records.get_email_from_reg(user.id)

        # Add user to verified database
        records.add_verified_user(user.id, email, user.name)

        # Assign user with all given roles
        roles = records.get_roles(email)
        roles.append('verified')
        await assign_user_roles(user, roles)
        
        ## Send the user a message that they have been verified and the next steps
        await ctxt.send(ephemeral=True,
                        content=f"Welcome {records.get_first_name(email)}! \nYou have been verified. Please check the {bot.get_guild(config.discord_guild_id).get_channel(config.discord_start_here_channel_id).mention} channel for next steps.")
        return
    # -----------------------------------------------------------------------------------------

    #Confirm user is registered
    if not records.registered_user_exists(email):
        await ctxt.send(ephemeral=True,
                        content=f"There are no user's registered with the email: `<{email}>`. \nPlease verify using the correct email, reregister at {config.contact_registration_link}, or contact administration.")
        return
    
    #Check if user is already verified
    if records.verified_user_exists(user.id):
        first_name = records.get_first_name(records.get_verified_email(user.id))
        await ctxt.send(ephemeral=True,
                        content=f"Welcome, {first_name}! You are already verified.")
        return

    # Check if email is in verified DB
    if records.verified_email_exists(email):
        await ctxt.send(ephemeral=True,
                        content=f"A User with that email address is already verified. \nPlease reregister with a different email address at {config.contact_registration_link}")
        return

    """ Happy Case: Send user an email with a one-time code """

    # Add user_id to registered user
    records.update_reg_discord_id(email, user.id)

    # Remove any codes from same user so only newest link will work
    records.remove_user_codes(user.id)

    # Send Verification Info to web for update
    CODE = generate_random_code(6)
    while records.code_exists(CODE):
        CODE = generate_random_code(6)

    if(await send_verification_email(email, CODE, user.name)):
        # add code to verification codes and send message
        records.add_code(CODE, user.id)
        await ctxt.send(ephemeral=True,
                        content=f"Check your inbox for an email from `<{config.email_address}>` with a verification link. Please check your email and enter the code in this format \n `/verify (code)`")
    else:
        await ctxt.send(ephemeral=True,
                        content="Failed to send verification email. Please contact an organizer for assistance.")

    ## Wait for timeout then delete verification code
    await asyncio.sleep(config.email_code_expiration_time)
    records.remove_code(CODE)

# -------------------------------------------------------------------------------------
'''
* @requires
    - User sending command is admin (check role)
* @ensures
    - User gains assigned role
    - Database is updated accordingly 
        (if user doesn't exist, add them with role, if they do exist, update role)
'''
@commands.has_role(config.discord_organizer_role_id)
@bot.hybrid_command(description="Manually verify a Discord account for this event (Organizers only)") 
async def overify(ctxt, flags: registerFlag): #TESTED
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
    admin_user = ctxt.author

    user = flags.member
    email = flags.email
    role = flags.role

    # Ensure user is an organizer
    organizer_role = ctxt.guild.get_role(config.discord_organizer_role_id)
    if not organizer_role in admin_user.roles:
        await ctxt.send(ephemeral=True,
                        content=f"You do not have permission to run this command")
        return
    
    #Check if role is valid to be overified with
    if not (role in role_map):
        await ctxt.send(ephemeral=True,
                        content=f"`<{role}>` is not a valid role. \nPlease chose either `participant`, `mentor`, or `judge`")
        return
    

    # Check if user is already verified
    if records.verified_user_exists(user.id):
        verified_email = records.get_verified_email(user.id)

        #Check if user has role specified, else add it
        if role in records.get_roles(verified_email):
            await ctxt.send(ephemeral=True,
                            content=f"`<{user.name}>` is verified and already has the role `<{role}>`.")
            return

        # Assign user the role
        await assign_user_roles(user, [role])
    
        # Update user in database
        roles = records.get_roles(verified_email)
        if not (role in roles):
            roles.append(role)
            records.reassign_roles(email, roles)
        
        await ctxt.send(ephemeral=True,
                        content=f"`<{user.name}>` is already verified but has been given the role `<{role}>`.")
        return

    # If User is not registered, add a registered user with no data
    if not records.registered_user_exists(email):
        records.add_registered_user(email, [role], {})
    
    # Add user to verified database
    records.add_verified_user(user.id, email, user.name)

    await assign_user_roles(user, [role, 'verified'])

    await ctxt.send(ephemeral=True,
                    content=f"`<{user.name}>` has been verified and given the role `<{role}>`.")
overify.error(handle_permission_error)

@bot.hybrid_command(description="Create a new team for this event")
async def createteam(ctxt, flags: teamNameFlag): #TESTED 
    """
    Creates a new team, assigning user to team and creating necessary roles and channels

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (teamNameFlag): The flags passed containing the team name. 
        
    Requires:
        - cannot already be in team
        - user has to be verified and participant
        
    """

    # Retrieve Context
    user = ctxt.author
    team_name = flags.teamname

    # Check that user is verified
    if not records.verified_user_exists(user.id):
        await ctxt.send(ephemeral=True,
                        content="You are not verified! Please verify yourself with the /verify command")

    # Check that user is not in another team
    if records.is_member_on_team(user.id):
        await ctxt.send(ephemeral=True,
                        content="You are already on a team. You can leave with the /leaveteam command")
        return

    # Check that team doesn't already exist
    if records.team_name_exists(team_name):
        await ctxt.send(ephemeral=True,
                        content="That team name is already in use. Please chose a different name")
        return

    # Create Team Role create channel permissions
    team_role = await ctxt.guild.create_role(name=team_name)

    # Sets up permissions:
    #   - all_access_pass role -> can view channel
    #   - @everyone -> cannot view channel
    #   - team_role -> can view channel
    category_channel_perms = {
        ctxt.guild.get_role(config.discord_all_access_pass_role_id): discord.PermissionOverwrite(view_channel=True),
        ctxt.guild.default_role: discord.PermissionOverwrite(view_channel=False),  
        team_role: discord.PermissionOverwrite(view_channel=True),               
    } 
    voice_channel_perms={
        team_role: discord.PermissionOverwrite(connect=True, view_channel=True, speak=True),
        ctxt.guild.get_role(config.discord_all_access_pass_role_id): discord.PermissionOverwrite(connect=True, view_channel=True, speak=True),
        ctxt.guild.default_role:  discord.PermissionOverwrite(view_channel=False)
    }

    # Create Channels
    category_channel = await ctxt.guild.create_category_channel(f"Team ## - {team_name}", overwrites=category_channel_perms)
    text_channel = await category_channel.create_text_channel(f"{team_name.replace(' ','-')}-text") # Inherit perms from Category
    voice_channel = await category_channel.create_voice_channel(f"{team_name.replace(' ','-')}-voice", overwrites=voice_channel_perms)

    # Create Team in Database
    channels = {
        'category': category_channel.id,
        'text': text_channel.id,
        'voice': voice_channel.id,
        'role': team_role.id
    }

    team_id = records.create_team(team_name, channels)
    records.join_team(team_id, user.id) # Add user to team

    # Assign role to user and send confirmation message
    await category_channel.edit(name=f"Team {team_id} - {team_name}")
    await user.add_roles(team_role)
    await user.add_roles(ctxt.guild.get_role(config.discord_team_assigned_role_id))
    await ctxt.send(ephemeral=True,
                    content=f'Team creation succeeded. {team_role.mention} created. Make sure to add members to your team using the `/addmember` command. Teams with fewer than 2 members will be deleted after {round(TEAM_FORMATION_TIMEOUT/60)} minutes.')

    # Wait for team timeout
    await asyncio.sleep(TEAM_FORMATION_TIMEOUT)
    await handle_team_formation_timeout(ctxt, team_id)

@bot.hybrid_command(description="Leave your current team")
async def leaveteam(ctxt): #TESTED 
    """
    Command for a user to leave their current team. 
    The user will:
        - be removed from the team
        - have team roles removed
    
    Team channel will be notified of departure. If not members are left, the team will be fully deleted.
    
    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
    """
    # Check that member is on a team
    user = ctxt.author

    # Ensure user is on a team
    if not records.is_member_on_team(user.id):
        await ctxt.send(ephemeral=True,
                        content="You cannot leave a team since you are not assigned to one!")
        return

    team_id = records.get_user_team_id(user.id)
    role_id = records.get_team(team_id)['channels']['role']

    team_assigned_role = ctxt.guild.get_role(config.discord_team_assigned_role_id)
    team_role = ctxt.guild.get_role(role_id)
    team_text_channel = ctxt.guild.get_channel(records.get_team(team_id)['channels']['text'])

    # Remove user from team in Database
    records.drop_team(user.id)

    # Remove role from user
    await remove_roles(user, [team_role, team_assigned_role])
    
    # Send message back confirming removal
    await ctxt.send(ephemeral=True,
                    content=f"You have successfully been removed from the team {team_role.mention}")
    await team_text_channel.send(content=f'{user.mention} has left the team.')

    # Delete team if no one is left
    if records.get_team_size(team_id) == 0:
        await delete_team_channels(team_id)

'''
* @requires
    - Member is in the server
    - Member is not currently in a team
    - Member is Verified and Participant
* @ensures
    - Member is added to team in db
    - Member is given the team role
    - Send message to team channel
'''
@bot.hybrid_command(description="Add a member to your team")
async def addmember(ctxt, flags: userFlag): #TESTED
    """
    Adds a specified member to the team of the user who invokes the command.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction.
        flags (userFlag): The user specified in the command input.
    """
    team_user = ctxt.author # User who invoked the command
    added_user = flags.member # The user to be added to the taem

    # Check that team_user is in a team
    if not records.is_member_on_team(team_user.id):
        await ctxt.send(ephemeral=True,
                        content='Failed to add team member. You are not currently in a team. You must be in a team to add a team member. Please use `/createteam` to create a team or have another participant use `/addmember` to add you to their team')
        return
    
    # Check that team is not full
    team_id = records.get_user_team_id(team_user.id)
    if records.get_team_size(team_id) >= MAX_TEAM_SIZE:
        await ctxt.send(ephemeral=True,
                        content=f'Failed to add team member. There is no space in your team. Teams can have a maximum of {MAX_TEAM_SIZE} members.')

    # Check that added_user is verified and a participant
    if not (records.verified_user_exists(added_user.id) and records.user_is_participant(added_user.id)):
        await ctxt.send(ephemeral=True,
                        content=f'Failed to add team member. `@{added_user.name}` is not a verified participant. All team members must be verified participants.')
        return
    
    # Check that added_user is not on a team
    if records.is_member_on_team(added_user.id):
        await ctxt.send(ephemeral=True,
                        content=f'Failed to add team member. {added_user.mention} is already in a team. To join your team, they must leave their current team.')
        return
    
    # Add the member to the team
    records.join_team(team_id, added_user.id)

    # Retrieve the team text channel and role
    text_channel = ctxt.guild.get_channel(records.get_team(team_id)['channels']['text'])
    team_role = ctxt.guild.get_role(records.get_team(team_id)['channels']['role'])

    # Assign added user team and team_assigned role
    await added_user.add_roles(team_role)
    await added_user.add_roles(ctxt.guild.get_role(config.discord_team_assigned_role_id))
    
    # Send confirmation message to team_user
    await ctxt.send(ephemeral=True,
                    content=f'Team member added successfully. {added_user.mention} has been added to {team_role.mention}.')
    
    # Notify team in team text channel of new member
    await text_channel.send(content=f'{added_user.mention} has been added to the team by {team_user.mention}.')

'''
* @requires
    - Must be an admin
    - Must provide 2 arguments for (previous name, new name)
* @ensures
    - Team name is altered in db
    - Role name is changed
    - Users are assigned the new role
    - Channel names are changed
'''

# @commands.has_role(config.discord_organizer_role_id)
# @bot.hybrid_command(description="Rename a team") #TODO
# async def renameTeam(ctxt, flags: teamNameFlag):
#     pass 
# renameteam.error(handle_permission_error)
'''
* @requires
    - User calling command is in the team or an admin
* @ensures
    - Team is removed from Databse
    - Discord Channels are removed
    - Roles are removed from Users
'''
@commands.has_role(config.discord_organizer_role_id)
@bot.hybrid_command(description="Remove Team (Organizers only)") 
async def deleteteam(ctxt, flags: removeTeamFlag):
    """
    Delete a team and its associated data from the event.

    Args:
        ctxt (discord.Interaction): The Context of the Interaction
        flags (removeTeamFlag): Flags containing the 'team_role' and 'reason' for removal
    """
    # Retrieve team role, name, and ID
    user = ctxt.author
    team_role = flags.team_role
    team_name = team_role.name
    team_id = records.get_team_id(team_name)

    # Retrieve reason and team members
    reason = flags.reason
    members = records.get_team_members(team_id)

    # Ensure user is an organizer
    organizer_role = ctxt.guild.get_role(config.discord_organizer_role_id)
    if not organizer_role in user.roles:
        await ctxt.send(ephemeral=True,
                        content=f"You do not have permission to run this command")
        return

    # Remove roles from users and drop members from team
    for member in members:
        curr_user = ctxt.guild.get_member(member[0])
        await remove_roles(curr_user, [team_role, ctxt.guild.get_role(config.discord_team_assigned_role_id)])
        records.drop_team(curr_user.id)

    # Delete team channels and db
    await delete_team_channels(team_id)

    # Notify team and admin about removal.
    await ctxt.send(ephemeral=True,
                    content=f"The team `<{team_name}>` has been removed and the members have been notified")
    
    for member in members:
        await ctxt.guild.get_member(member[0]).send(
            content=f"Your team has been removed from the event. \nReason: `{reason}`. \nYou may create a new team but continued failure to comply may result in being permanently removed")
deleteteam.error(handle_permission_error)

#When the bot is ready, this automatically runs
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.tree.sync()

def start():
    bot.run(config.discord_token)
# ------------------------------------------------------------------


