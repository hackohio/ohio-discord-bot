import csv
import records
import os
import pandas as pd
import discord

#For all teams in the teamDB, get teamName and all users associated with it
# TeamData = [Team ID, TeamName, Members...]

EXPORT_FILENAME = 'team_export.csv'

# ----------- Grab Team Data from DB ------------- #
def get_team_data():
    HIGHEST_TEAM_ID = records.get_max_team_id()
    team_data_list = []

    #Add Header to List
    headers = ['Team ID', 'Team Name', 'Members...']
    team_data_list.append(headers)

    for team_id in range(HIGHEST_TEAM_ID):
        team_data = []
        #If the team exists
        if (records.team_exists(team_id)):
            #Store id and name
            team_data.append(team_id)
            team_data.append(records.get_team_name(team_id)) 

            #Look for members TODO: Turn member_id into discord username
            team_members = records.get_team_members_emails(team_id)
            for member in team_members:
                #Clean Email
                team_data.append(str(member)[2:-3])

            #Append to data list≠
            team_data_list.append(team_data)

    return team_data_list



# ----------- Export Data to CSV --------------- #
def export_to_csv(EXPORT_FILENAME:str, data: list):
    #Remove file if it exists so it can be overwritten
    if os.path.isfile(EXPORT_FILENAME): os.remove(EXPORT_FILENAME)

    with open(EXPORT_FILENAME, 'w') as csv_file:
        #Export Header Items
        writer = csv.writer(csv_file)

        #Add Rows of Data
        for row in data:
            writer.writerow(row)
        
        csv_file.close()


def append_to_xlsx(EXPORT_FILENAME:str, sheets:list[str]):
    if os.path.isfile(EXPORT_FILENAME): os.remove(EXPORT_FILENAME)

    # Create a new Excel writer object
    with pd.ExcelWriter(EXPORT_FILENAME, engine='xlsxwriter', mode='w') as writer:
        # Write the CSV data to a new sheet
        for sheet in sheets:
            #Import csv data as sheet to excel file
            csv_file = pd.read_csv(sheet)
            csv_file.to_excel(writer, sheet_name=sheet.replace('.csv',''), index=False)

    #Remove CSV files
    for file in sheets:
        os.remove(file)




#Retrieve Data
team_data_list = get_team_data()


#Compile into CSV
sheets = []

export_to_csv('team_export.csv', team_data_list)
sheets.append('team_export.csv')


#Compile into Excel
# append_to_xlsx('Report.xlsx', sheets)











