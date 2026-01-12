import records
import config

from flask import Flask, request, jsonify
from eventlet import wsgi
import eventlet

import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) 
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Logs everything of INFO level and above to a file
file_handler = logging.FileHandler('web.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Logs only WARNING level and above to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

'''
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
        'roles': "role,role", (comma-separated)        
    }
}
'''

ROLE_MAP = {
    '1': 'judge',
    '2': 'mentor'
}

#Define the server as app
app = Flask(__name__)

#Setup a method to listen at "/post/user" for a post request
@app.route("/post/user", methods=['POST'])
def push_user():

    # 1. Ensure API-KEY is correct      
    if (request.headers.get('api-key') != config.web_api_key):
        logging.error("Api-Key is not correct.")
        return jsonify({"error": "API-Key is not correct."}), 401
       
    # 2. Retrieve Data from Request
    data = request.get_json()
    
    # 3. Check that email is present
    email = data.get("email", "").lower()
    if not email:
        logging.error("Email is required.")
        return jsonify({"error": "Email is required"}), 400

    # 4. Grab and process roles info
    roles = []
    roles_input = data.get("roles", "")
    if roles_input:
        for role in roles_input.split(','):
            role = role.strip()  
            if role in ROLE_MAP and (role not in roles):  
                roles.append(ROLE_MAP.get(role))        
    if len(roles) == 0: roles.append('participant') # No roles -> participant
    
    first_name = data.get("first_name", "Brutus")
    last_name = data.get("last_name", "Buckeye")
    is_capstone = data.get("is_capstone", 0)

    
    # 5. Add Registered User to Database
    try:
        #Add User to registrant list
        records.add_registration(email, first_name, last_name, is_capstone, roles)

        #Send back "Good" Message
        logging.info(f"User registered successfully: {email} with roles {roles}")
        return jsonify({"email": email, "first_name": first_name, "last_name":last_name, "is_capstone": is_capstone, "roles": roles}), 201
    
    except Exception as e:
       
        #Send Error that user being added has failed
        logging.exception(f"An unexpected error occured while adding user to database: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500


# Method to start a server and wait for a request
def start():
    wsgi.server(eventlet.listen(('0.0.0.0', config.web_port)), app)


