import records
import csv


'''
- Pull Data from CSV file
- For every entry, call the add_participant() method
'''
# IF: file is importing participants, it MUST have 'participant' in the name
# ELSE: file is treated as containing leaders 

FILENAME = "leaders.csv" 
ATTR_DIS = "Discord ID"
ATTR_EMAIL = "Email"

#FILENAME = "participants.csv" 
#ATTR_DIS = "What is your Discord username?"
#ATTR_EMAIL = "Username"

with open(FILENAME, 'r') as csv_file:
    #Attempt to Read file
    try:
        reader = csv.DictReader(csv_file, delimiter=",")
    except:
        raise BaseException("Cannot read/import csv file. Check format and resubmit")
    
    #Search through file for relevant user data
    userNum = 0
    for user in reader:
        userData = {}
        userData['role'] = []
        
        #Gather email and discord_username
        for attr in user:

            #Find Discord Username
            if(attr == ATTR_DIS and user[attr] != ""):
                userData['discord_username'] = user[attr].replace(" ","")

            #Find Email Address
            if(attr == ATTR_EMAIL and user[attr] != ""):
                userData['email'] = user[attr].replace(" ", "")

            #Find Role
            if('participant' in FILENAME.lower()):
                userData['role'].append('participant')
            else:
                #Look for both mentor and judge
                if ('mentor' in user[attr].lower()):
                    userData['role'].append('mentor')
                if ('judge' in user[attr].lower()):
                    userData['role'].append('judge')
 
        # Use UserData to add user to DB
        ## Check if all user fields are filled
        if('email' in userData and 'discord_username' in userData and 'role' in userData):
            ## Determine if user is a (particpant, mentor, or judge)
            if ('participant' in userData['role']):
                if not (records.participant_response_exists(userData['email'].lower(), userData['discord_username'])):
                    try:
                        records.add_participant_response_entry(userData['email'].lower(), userData['discord_username'])
                        print(f'Participant {userNum} Added: <{userData["email"]}>')
                    except:
                        print("Error adding user to DB")
                        break

            if ('mentor' in userData['role']):
                if not (records.mentor_response_exists(userData['email'].lower(), userData['discord_username'])):
                    try:
                        records.add_mentor_response_entry(userData['email'].lower(), userData['discord_username'])
                        print(f'Mentor {userNum} Added: <{userData["email"]}>')
                    except:
                        print("Error adding user to DB")
                        break

            if ('judge' in userData['role']):
                if not (records.judge_response_exists(userData['email'].lower(), userData['discord_username'])):
                    try:
                        records.add_judge_response_entry(userData['email'].lower(), userData['discord_username'])
                        print(f'Judge {userNum} Added: <{userData["email"]}>')
                    except:
                        print("Error adding user to DB")
                        break
        userNum = userNum + 1
        

    
    