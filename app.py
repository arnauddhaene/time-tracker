import dash
import dash_core_components as dcc
import dash_html_components as html
import plotly.express as px
import pandas as pd
import numpy as np
import datetime as dt
from dateutil.parser import isoparse
import pickle
import os.path
import seaborn as sns
import matplotlib.pyplot as plt
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']

# scope
scopes = ['https://www.googleapis.com/auth/calendar']
visium_calendar_id = "bjaqb1128v8fgrknb29d8r07is@group.calendar.google.com"

def get_service(calendar_name='personal'):
    """Shows basic usage of the Google Calendar API.
    Prints the start and name of the next 10 events on the user's calendar.
    """
    creds = None
    
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(f'{calendar_name}-token.pickle'):
        with open(f'{calendar_name}-token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                f'{calendar_name}-credentials.json', scopes)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(f'{calendar_name}-token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)

def get_events(service, calendar_id='primary'):
    
    # Setting now time
    now = dt.datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time
    # Getting Monday 5 AM
    today = dt.date.today()
    monday = today - dt.timedelta(days=60)
    week_start = dt.datetime.combine(monday, dt.time(5,0)).isoformat() + 'Z'
    
    return service.events().list(
        calendarId=calendar_id, orderBy='startTime',singleEvents=True, 
        timeMin=week_start, timeMax=now
    ).execute()

def pre_process(raw):
    # Copy DataFrame
    processed = raw.copy()
    
    # Drop unwanted columns
    for col in processed.columns:
        if col not in ['start', 'end', 'summary', 'colorId', 'location', 'attendees']:
            del processed[col]

    # Drop automated calendar events for Home Office by Lucca       
    processed.drop(processed[processed.summary == "Home office"].index, inplace=True)
            
    # TODO: verify that this modif is okay and doesn't miss out on anything
    idx = pd.isna([date.get('dateTime') for date in processed['end']])
    processed.drop(
        processed[idx].index,
        inplace=True
    )

    # Dates
    processed['end'] = [isoparse(date.get('dateTime')) for date in processed['end']] 
    processed['start'] = [isoparse(date.get('dateTime')) for date in processed['start']]

    processed['duration'] = processed['end'] - processed['start']
    processed['duration'] = [td.seconds / 3600 for td in processed['duration']]


    processed['datetime'] = pd.to_datetime(processed['start'], utc=True)
    processed['date'] = processed['datetime'].dt.date
    del processed['start']
    del processed['end']

    if 'colorId' in raw.columns:
        # colorId mapping
        processed['colorId'] = raw['colorId'].fillna(0)
        processed['colorId'] = processed['colorId'].astype(int)

        # create activity col
        activity = ['default'] * 12
        activity[4] = 'meditation'
        activity[7] = 'gym'
        activity[11] = 'DAG'

        processed['activity'] = [ activity[colorId] for colorId in processed['colorId'] ]

    if 'attendees' in raw.columns:
        # count attendees
        processed['attendees'] = raw['attendees'].fillna(1)
        processed['attendees'] = [1 if attendees == 1 else len(attendees) for attendees in processed['attendees']]

    return processed

visium_events = pd.DataFrame(data=get_events(get_service(), calendar_id=visium_calendar_id).get('items', []))

v_events = pre_process(visium_events)
v_events['activity'] = ['Work'] * v_events.shape[0]

personal_events = pd.DataFrame(data=get_events(get_service(), calendar_id='primary').get('items', []))

p_events = pre_process(personal_events)

events = pd.concat([v_events, p_events])

fig = px.bar(events, x='date', y='duration', color='activity')

app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

app.layout = html.Div(children=[
    html.H1(children='Time Tracker'),

    html.Div(children='''
        Tracking the time I work. These include only what is noted on my calendar, which I have started to fill in consistently since October.
    '''),

    dcc.Graph(
        id='example-graph',
        figure=fig
    )
])

if __name__ == '__main__':
    app.run_server(debug=True)