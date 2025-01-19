import records
import config
import bot

from flask import Flask, abort, request, jsonify
from eventlet import wsgi
import eventlet



'''
The purpose of this file is to stay active and listen for any incoming post requests from 
the Qualtrics Workflow that should send the bot a request to update the userDB anytime someone 
registers for the event. This will keep the db up-to-date with new registrations

Format for Post Requests JSON
{
    header: {
        'Api-Key': str
    }
    body: {
        'email': str,
        'roles': (role,role), (comma-separated)
        
        'data-header':'data-contents' (Every other pair is considered data)
        ...
    }
}
"""
'''

#Define the server as app
app = Flask(__name__)

#Setup a method to listen at "/post/user" for a post request
@app.route("/post/user", methods=['POST'])
def push_user():
    #Check that API key is correct
    if (request.headers.get('Api-Key') == config.web_api_key):
       
        ROLE_MAP = {
            '1': 'judge',
            '2': 'mentor'
        }
        
        #Retrieve Data from Request
        data = request.get_json()
        
        # Email is required
        email = data.get("email", "").lower()

        if not email:
            return jsonify({"Error": "Email is required"}), 400
        
        if data.get("isAdultOrOSU") == 2:
            return jsonify({"Error": "Participant not allowed"}), 400
        
        # Get the 'roles' data from the input, defaulting to an empty string if not found
        roles_input = data.get("roles", "")

        # Initialize an empty list to store the roles
        roles = []

        # If role_input is not empty, process the roles
        if roles_input:
            # Split the input into individual role strings (by comma), and process each one
            for role in roles_input.split(','):
                role = role.strip()  # Clean up any extra spaces around the role
                if role in ROLE_MAP and (role not in roles):  # Only consider valid roles
                    roles.append(ROLE_MAP.get(role))  # Add the corresponding role name to the list        
        
        # If there is no roles at this point, it is because they're a participant
        if len(roles) == 0:
            roles.append('participant')
        
        user_data = {
            "first_name": data.get("firstName"),
            "last_name": data.get("lastName"),
            "university": data.get("university"),
            "class_team": data.get("classTeam"),
            "major": data.get("major"),
            "grad_year": data.get("gradYear"),

            # Mentor/Judge Specific Form Data Starts Here
            "company": data.get("company"),
            "job_title": data.get("jobTitle"),
        }
        
        #Append Data to Database 
        try:
            #Add User to registrant list
            records.add_registered_user(email, roles, user_data)

            #Send back "Good" Message
            return jsonify({"email": email, "roles": roles, "data": user_data}), 200
        except Exception as e:
            #Send Error that user being added has failed
            print(f"ERROR {e}: Not all data in the request was included or error with DB file")
            return jsonify({f"Error: {e}"}), 400
    else:
        #Send Error that Api-Key is not correct
        print("ERROR: Api-Key is not correct.")
        return jsonify({"ERROR: Api-Key is not correct."}), 401

#Method to start a server and wait for a request
def start():
    wsgi.server(eventlet.listen(('0.0.0.0', config.web_port)), app)


