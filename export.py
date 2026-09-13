import sqlite3
import pandas as pd


def get_teams_dataframe(conn) -> pd.DataFrame:
    query = """
    SELECT 
        t.id AS team_id,
        t.name AS team_name,
        GROUP_CONCAT(v.email, ', ') AS member_email
    FROM 
        teams t
    JOIN 
        verified v ON t.id = v.team_id
    JOIN 
        registration r ON r.discord_id = v.discord_id
    GROUP BY
        t.id;
    """

    df = pd.read_sql_query(query, conn)

    df_split = df['member_email'].str.split(', ', expand = True)
    df_split.columns = [f'Member {i+1} Email' for i in range(df_split.shape[1])]

    df_final = pd.concat([df['team_id'], df[['team_name']], df_split], axis=1)
    df_final.rename(columns={'team_id': "Team Number", 'team_name': 'Team Name'}, inplace=True)
    
    return df_final

def get_participants_dataframe(conn) -> pd.DataFrame:
    main_query = """
    SELECT 
        CAST(v.discord_id AS TEXT) AS discord_id, 
        v.username, 
        v.email, 
        v.team_id
    FROM verified v
    JOIN registration r ON v.discord_id = r.discord_id
    WHERE is_participant;
    """
    data_query = """
    SELECT *
    FROM data d
    JOIN registration r USING(email)
    WHERE is_participant;
    """

    df = pd.read_sql_query(main_query, conn)
    data_df = pd.read_sql_query(data_query, conn)
    df_final = pd.concat([data_df['first_name'], data_df['last_name'], 
                        df['email'], df['team_id'], df['username'], 
                        data_df['major'], data_df['grad_year']], axis=1)
    df_final.columns = ['First Name', 'Last Name', 'Email', 'Team Number', 
                'Username', 'Major', 'Grad Year']

    return df_final


def main():
    FILE_PATH = 'participants.xlsx'
    conn = sqlite3.connect('records.db')

    # Create/overwrite excel file
    get_teams_dataframe(conn).to_excel(FILE_PATH, sheet_name='Teams', index=False)

    # Open excel file in 'append' mode
    with pd.ExcelWriter(FILE_PATH, mode='a', engine='openpyxl') as writer:
        get_participants_dataframe(conn).to_excel(writer, sheet_name='Participants', index=False)

    print(f"Exported to {FILE_PATH}")
    conn.close()

if __name__ == "__main__":
    main()
