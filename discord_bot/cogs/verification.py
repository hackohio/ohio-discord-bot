"""Verification, email, and role synchronization commands."""

import asyncio
import logging
import random
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import discord
from discord import app_commands
from discord.ext import commands

import config
import records
from discord_bot.common import _log_rejection, audit_command

logger = logging.getLogger(__name__)

role_map = {
    "participant": config.discord_participant_role_id,
    "mentor": config.discord_mentor_role_id,
    "judge": config.discord_judge_role_id,
    "verified": config.discord_verified_role_id,
    "all-access": config.discord_all_access_pass_role_id,
}

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
    return "".join(secrets.choice(characters) for _ in range(n))


async def sync_user_roles(member: discord.Member):  # TESTED
    """
    Full Sync:
    1. Looks at every role defined in role_map.
    2. Adds it if the DB says they should have it.
    3. Removes it if the DB says they shouldn't (and they currently do).
    """

    identity = {
        "guild_id": getattr(member.guild, "id", None),
        "actor_id": member.id,
        "actor_username": member.name,
        "actor_display_name": member.display_name,
    }
    # Check that member is verified and capable of having roles assigned
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
    expected_role_ids = []

    # Iterate through the roles we manage (role_map)
    for role_name, role_id in role_map.items():
        should_have = role_name in should_have_names
        if should_have:
            expected_role_ids.append(role_id)

        discord_role = member.guild.get_role(role_id)
        if not discord_role:
            logger.warning(
                "role_sync_resource_missing role_name=%r role_id=%r actor_id=%r guild_id=%r",
                role_name,
                role_id,
                identity["actor_id"],
                identity["guild_id"],
            )
            continue

        # Check if user has this role currently
        has_role = discord_role in member.roles

        # Check if they satisfy the requirement in the DB
        # LOGIC:
        if should_have and not has_role:
            roles_to_add.append(discord_role)
        elif not should_have and has_role:
            roles_to_remove.append(discord_role)

    # 3. Apply Changes (Bulk operations are faster/safer)
    try:
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            logger.info(
                "discord_role_mutation_completed operation='add_roles' role_ids=%r actor_id=%r guild_id=%r",
                [role.id for role in roles_to_add],
                identity["actor_id"],
                identity["guild_id"],
            )
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            logger.info(
                "discord_role_mutation_completed operation='remove_roles' role_ids=%r actor_id=%r guild_id=%r",
                [role.id for role in roles_to_remove],
                identity["actor_id"],
                identity["guild_id"],
            )
    except Exception:
        logger.exception(
            "discord_role_mutation_failed actor_id=%r", identity["actor_id"]
        )
        raise


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
    first_name = records.get_first_name(recipient) or "there"
    expiration_minutes = round(config.email_code_expiration_time / 60)
    plain_body = f"""Hi {first_name},

Use this code to verify the Discord account {username}:

{CODE}

This code expires in {expiration_minutes} minutes.
If you did not request this, you can safely ignore this email.

OHI/O Hackathon Team
Questions? Contact {config.contact_organizer_email}
"""
    html_body = f"""<!doctype html>
<html lang="en">
  <body style="margin:0;background-color:#f4f4f4;color:#242629;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f4;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.08);">
            <tr>
              <td style="background-color:#ba0c2f;padding:24px 32px;color:#ffffff;">
                <div style="font-size:14px;font-weight:bold;letter-spacing:1.5px;">OHI/O HACKATHONS</div>
                <h1 style="margin:8px 0 0;font-size:26px;line-height:1.25;">Verify your Discord account</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">Hi {escape(str(first_name))},</p>
                <p style="margin:0 0 24px;font-size:16px;line-height:1.6;">
                  Enter this code in Discord to connect your registration to
                  <strong>{escape(str(username))}</strong>.
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td align="center" style="background-color:#f8e8ec;border:1px solid #e7a8b7;border-radius:8px;padding:20px;font-size:32px;font-weight:bold;letter-spacing:8px;color:#7a001d;">
                      {escape(str(CODE))}
                    </td>
                  </tr>
                </table>
                <p style="margin:24px 0 8px;font-size:14px;line-height:1.6;color:#555555;">
                  This code expires in <strong>{expiration_minutes} minutes</strong>.
                </p>
                <p style="margin:0;font-size:14px;line-height:1.6;color:#555555;">
                  If you did not request this, you can safely ignore this email.
                </p>
              </td>
            </tr>
            <tr>
              <td style="background-color:#f7f7f7;padding:20px 32px;font-size:12px;line-height:1.5;color:#666666;">
                OHI/O Hackathon Team<br>
                Questions? Contact {escape(config.contact_organizer_email)} or message Ask an Organizer in Discord.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your OHI/O Discord verification code"
    msg["From"] = config.email_address
    msg["To"] = recipient
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    def send():
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp_server:
            smtp_server.login(config.email_address, config.email_password)
            smtp_server.sendmail(config.email_address, recipient, msg.as_string())

    try:
        await asyncio.to_thread(send)
        logger.info(
            "verification_email_delivered email=%r username=%r outcome=%r",
            recipient,
            username,
            "sent",
        )
        return True
    except Exception:
        logger.exception("verification_email_delivery_failed email=%r", recipient)
        return False


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="affirm", description="Recieve a random affirmation for encouragement"
    )
    @audit_command
    async def affirm(self, interaction: discord.Interaction):
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
    @app_commands.describe(
        email_or_code="Email Address used to Register / or / Verification Code"
    )
    @app_commands.command(
        name="verify", description="Verify your Discord account for this Event"
    )
    @audit_command
    async def verify(self, interaction: discord.Interaction, email_or_code: str):  # TESTED
        """
        Verifies a user's Discord account by linking it with their reg email

        This function:
        1. Checks if the email is registered
        2. Checks if user is already verified
        3. Checks if email is already associated with a verified account
        4. Associates the user's Discord ID with email if they are registered but not yet verified
        5. Sends a verification code via email and stores its expiration time

        Args:
            ctxt (Context): The Context of the Interaction
            flags (emailFlag): Flag containing email address to be verified
        """

        user = interaction.user
        await interaction.response.defer(
            ephemeral=True
        )  # Tell discord to wait before crashing session

        # Check if user is already verified
        if records.is_verified(user.id):
            _log_rejection(interaction, "already_verified")
            first_name = records.get_first_name(records.get_verified_email(user.id))
            await interaction.edit_original_response(
                content=f"Welcome, {first_name}! You are already verified."
            )
            return

        # Case 1: CODE was entered (Check Code)
        if email_or_code.isdigit():
            code = email_or_code

            # Check that code is valid and unexpired
            code_info = records.get_value_from_code(code)
            if not code_info:
                _log_rejection(interaction, "invalid_or_expired_code")
                await interaction.edit_original_response(
                    content="Your Verification Code is either not valid or has expired. Please request a new one.",
                )
                return

            # Check that user_id matches user entering the code
            if code_info["discord_id"] != user.id:
                _log_rejection(
                    interaction,
                    "code_belongs_to_another_user",
                    target_id=code_info["discord_id"],
                )
                await interaction.edit_original_response(
                    content="The code you entered is not associated with your discord account. Please request a new one by entering the email you registered with.",
                )
                return

            # ------------- Happy Case --------------------

            email = code_info["email"]

            # Add user to verified database
            if not records.add_verified_user(email, user.id, user.name):
                _log_rejection(interaction, "email_already_verified", email=email)
                await interaction.edit_original_response(
                    content="That email address is already linked to another Discord account.",
                )
                return
            records.remove_code(code)

            # Assign user with all given roles
            await sync_user_roles(user)

            # Send the user a message that they have been verified and the next steps
            await interaction.edit_original_response(
                content=f"Welcome {records.get_first_name(email)}! \nYou have been verified. Please check the {interaction.guild.get_channel(config.discord_start_here_channel_id).mention} channel for next steps.",
            )

        # Case 2: Email was entered
        else:
            email = email_or_code

            # Confirm user is registered
            if not records.is_registered(email):
                _log_rejection(interaction, "not_registered", email=email)
                await interaction.edit_original_response(
                    content=f"There are no user's registered with the email: `<{email}>`. \nPlease verify using the correct email, reregister at {config.contact_registration_link}, or contact administration.",
                )
                return

            # Check if email is in verified DB
            if records.is_verified(email):
                _log_rejection(interaction, "email_already_verified", email=email)
                await interaction.edit_original_response(
                    content=f"A User with that email address is already verified. \nPlease reregister with a different email address at {config.contact_registration_link}",
                )
                return

            # ------------- Happy Case --------------------

            # NOTE: DB automatically replaces any code entry that matches discord_id, code, or email
            # Send Verification Info to web for update
            CODE = generate_random_code(6)
            while records.code_exists(CODE):
                CODE = generate_random_code(6)

            if await send_verification_email(email, CODE, user.name):
                records.add_code(
                    email, user.id, CODE, config.email_code_expiration_time
                )
                await interaction.edit_original_response(
                    content=f"Check your inbox for an email from `<{config.email_address}>` with a verification link. Please check that email and enter the code in this format \n `/verify (code)`\n\nBe sure to check your junk folder if you have trouble finding it",
                )
            else:
                await interaction.edit_original_response(
                    content="Failed to send verification email. Please contact an organizer for assistance.",
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))

