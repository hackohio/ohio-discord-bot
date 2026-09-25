import logging
import secrets
import time
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request
from waitress import serve

import config
import records
from logging_config import configure_logging

logger = logging.getLogger(__name__)

"""
The purpose of this file is to stay active and listen for any incoming post requests from 
the Qualtrics Workflow that should send the bot a request to update the userDB anytime someone 
registers for the event. This will keep the db up-to-date with new registrations

Format for Post Requests JSON
{
    header: {
        'api-key': str
    }
    body: {
        'email': str,

        'first_name': str,
        'last_name': str,
        
        'is_capstone': bool,
        'is_professional': bool,
        'roles': "role,role", (comma-separated)        
    }
}
"""

ROLE_MAP = {"1": "judge", "2": "mentor"}

# Define the server as app
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "Request body must not exceed 16 KiB"}), 413


@app.before_request
def begin_request():
    g.request_id = uuid.uuid4().hex
    g.request_started_at = time.monotonic()
    logger.info(
        "webhook_request_received request_id=%r method=%r path=%r",
        g.request_id,
        request.method,
        request.path,
    )


@app.after_request
def finish_request(response):
    started_at = getattr(g, "request_started_at", time.monotonic())
    logger.info(
        "webhook_request_completed request_id=%r status=%r duration_ms=%r",
        getattr(g, "request_id", "unknown"),
        response.status_code,
        round((time.monotonic() - started_at) * 1000, 3),
    )
    return response


# Setup a method to listen at "/post/user" for a post request
@app.get("/health")
def health():
    if Path(config.discord_ready_file).is_file():
        return jsonify({"status": "ready"})
    return jsonify({"status": "starting"}), 503


@app.route("/post/user", methods=["POST"])
def push_user():
    request_id = g.request_id

    # 1. Ensure API-KEY is correct
    supplied_api_key = request.headers.get("api-key", "")
    if not secrets.compare_digest(supplied_api_key, config.web_api_key):
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "invalid_api_key",
        )
        return jsonify({"error": "API-Key is not correct."}), 401
    logger.debug("webhook_authenticated request_id=%r", request_id)

    # 2. Retrieve Data from Request
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "invalid_json",
        )
        return jsonify({"error": "JSON object is required"}), 400

    # 3. Check that email is present
    raw_email = data.get("email", "")
    email = raw_email.replace(" ", "").lower() if isinstance(raw_email, str) else ""
    if not email:
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "missing_email",
        )
        return jsonify({"error": "Email is required"}), 400

    # 4. Grab and process roles info
    roles = []
    roles_input = data.get("roles", "")
    if roles_input is not None and not isinstance(roles_input, str):
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "invalid_roles",
        )
        return jsonify({"error": "roles must be a comma-separated string"}), 400
    if roles_input:
        for role in roles_input.split(","):
            role = role.strip()
            mapped_role = ROLE_MAP.get(role)
            if mapped_role and mapped_role not in roles:
                roles.append(mapped_role)
    if len(roles) == 0:
        roles.append("participant")  # No roles -> participant

    first_name = data.get("first_name", "Brutus")
    last_name = data.get("last_name", "Buckeye")
    is_capstone = data.get("is_capstone", False)
    if not isinstance(is_capstone, bool):
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "invalid_is_capstone",
        )
        return jsonify({"error": "is_capstone must be a boolean"}), 400

    is_professional = data.get("is_professional", False)
    if not isinstance(is_professional, bool):
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "invalid_is_professional",
        )
        return jsonify({"error": "is_professional must be a boolean"}), 400
    try:
        records.get_category(is_capstone, is_professional)
    except ValueError:
        logger.warning(
            "webhook_request_rejected request_id=%r reason=%r",
            request_id,
            "invalid_categories",
        )
        return (
            jsonify(
                {"error": "is_capstone and is_professional cannot both be true"}
            ),
            400,
        )

    # 5. Add Registered User to Database
    try:
        records.add_registration(
            email,
            first_name,
            last_name,
            is_capstone,
            roles,
            is_professional=is_professional,
        )
        return (
            jsonify(
                {
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_capstone": is_capstone,
                    "is_professional": is_professional,
                    "roles": roles,
                }
            ),
            201,
        )

    except Exception:
        logger.exception(
            "registration_upsert_failed request_id=%r email=%r", request_id, email
        )
        return jsonify({"error": "An internal server error occurred."}), 500


# Method to start a server and wait for a request
def start():
    configure_logging("web")
    logger.info("webhook_starting port=%r", config.web_port)
    serve(app, host="127.0.0.1", port=config.web_port)
