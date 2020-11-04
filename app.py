import datetime as dt
import os.path
import pickle
import json

import dash
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output

import numpy as np
import pandas as pd
import plotly.express as px

from dateutil.parser import isoparse
from decouple import config
from flask import send_from_directory, request

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


def get_service(calendar_name='personal'):
    """Get Google Calendar API service from credentials

    Args:
        calendar_name (str, optional): Calendar name for file saving and
        credentials fetching. Defaults to 'personal'.

    Returns:
        service: Resource for interacting with Google Calendar API
    """
    creds = None

    client_secret_dict = dict(
        installed=dict(
            client_id=config('client_id'),
            project_id=config('project_id'),
            auth_uri=config('auth_uri'),
            token_uri=config('token_uri'),
            auth_provider_x509_cert_url=config('auth_provider_x509_cert_url'),
            client_secret=config('client_secret'),
            redirect_uris=config('redirect_uris').split(' ')
        )
    )

    with open(f'{calendar_name}-credentials.json', 'w') as fp:
        json.dump(client_secret_dict, fp)

    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.s
    if os.path.exists(f'{calendar_name}-token.pickle'):
        with open(f'{calendar_name}-token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secrets_file=f'{calendar_name}-credentials.json',
                scopes=[config('SCOPE')])
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(f'{calendar_name}-token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)


def get_events(service, calendar_id='primary'):
    """Get events from calendar using Google Calendar API service.

    Args:
        service (service): Resource for interacting with Google Calendar API
        calendar_id (str, optional): Google Calendar ID, your possibilities
        can be found by running `service.calendarList().list().execute()`.
        Defaults to 'primary'.

    Returns:
        dict: Response body for events call. Look for `items` key to fetch
        events list.
    """

    # Setting now time
    now = dt.datetime.utcnow()

    # Getting Monday September 7 at 5 AM
    internship_start = dt.datetime.combine(
        dt.date(2020, 9, 7), dt.time(5, 0)).isoformat() + 'Z'

    # Looks 1 week in the future
    return service.events().list(
        calendarId=calendar_id, orderBy='startTime', singleEvents=True,
        timeMin=internship_start,
        timeMax=(now + dt.timedelta(days=7)).isoformat() + 'Z'
    ).execute()


def pre_process(raw):
    """Pre-processing step for raw data. TODO: separate into files?

    Args:
        raw (pd.DataFrame): raw data

    Returns:
        pd.DataFrame: processed data
    """

    # Copy DataFrame
    processed = raw.copy()

    # Drop unwanted columns
    for col in processed.columns:
        if col not in ['start', 'end', 'summary',
                       'colorId', 'location', 'attendees']:
            del processed[col]

    # Drop automated calendar events for Home Office by Lucca
    processed.drop(processed[processed.summary ==
                             "Home office"].index, inplace=True)

    # TODO: verify that this modif is okay and doesn't miss out on anything
    idx = pd.isna([date.get('dateTime') for date in processed['end']])
    processed.drop(
        processed[idx].index,
        inplace=True
    )

    # Dates
    processed['end'] = [isoparse(date.get('dateTime'))
                        for date in processed['end']]
    processed['start'] = [isoparse(date.get('dateTime'))
                          for date in processed['start']]

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
        # TODO: incorporate Google Colors to plotly figure
        activity = ['Social'] * 12
        activity[2] = 'Personal projects'
        activity[4] = 'Meditation'
        activity[7] = 'Exercise'
        activity[11] = 'Associative'

        processed['activity'] = [activity[colorId]
                                 for colorId in processed['colorId']]

    # TODO: Visium has no attendee information, irrelevant?
    if 'attendees' in raw.columns:
        # count attendees
        processed['attendees'] = raw['attendees'].fillna(1)
        processed['attendees'] = [1 if attendees == 1 else len(
            attendees) for attendees in processed['attendees']]

    return processed


def fetch_events():
    """Fetch Events from both Calendars
    """
    # Fetch Visium Events
    visium_events = pd.DataFrame(data=get_events(
        get_service(), calendar_id=config('VISIUM_CAL_ID')).get('items', []))

    v_events = pre_process(visium_events)
    v_events['activity'] = ['Visium'] * v_events.shape[0]

    # Fetch Personal Events - from primary Google Calendar
    personal_events = pd.DataFrame(data=get_events(
        get_service(), calendar_id='primary').get('items', []))

    p_events = pre_process(personal_events)

    return pd.concat([v_events, p_events])

events = fetch_events()

# Stacked Bar Chart of duration summed by day
bar_stacked_fig = px.bar(events, x='date', y='duration', color='activity')
bar_stacked_fig.update_layout(title='Time spent')

# TODO: make this more modular
exercise_percentage = events[
    (events['activity'] == 'Exercise') &
    (events['date'] > dt.date.today() - dt.timedelta(days=7)) &
    (events['date'] < dt.date.today())
].duration.sum() / float(config('EXERCISE_GOAL')) * 100

meditation_percentage = events[
    (events['activity'] == 'Meditation') &
    (events['date'] > dt.date.today() - dt.timedelta(days=7)) &
    (events['date'] < dt.date.today())
].duration.sum() / float(config('MEDITATION_GOAL')) * 100

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SANDSTONE])
server = app.server

# ====================================================================
# APP LAYOUT
# ====================================================================

app.layout = html.Div(className="container mt-4 mb-5", children=[
    html.Link(
        rel='stylesheet',
        href='/static/circle.css'
    ),

    html.Div(
        className="row",
        children=[
            html.Div(
                className="col-12 mb-3",
                children=[
                    html.Div(
                        className="d-flex justify-content-between",
                        children=[
                            html.Div(
                                children=[
                                    html.H1(
                                        id='title',
                                        children="Arnaud's Time Tracker"
                                    ),

                                    html.Div(
                                        id='headline',
                                        children='''
                                            Headline/subtitle, TBD what I want exactly.
                                        '''
                                    ),
                                ]
                            ),

                            html.Button(
                                id='quit',
                                className='btn btn-danger',
                                children=['Quit']
                            )
                        ]
                    )
                ]
            )
        ]
    ),

    html.Div(
        className="row",
        children=[
            html.Div(
                className="col-12",
                children=[
                    html.Div(
                        className="d-flex justify-content-between",
                        children=[
                            html.Button(
                                id='refresh',
                                className="btn btn-primary",
                                children=[
                                    "Refresh"
                                ]
                            ),

                            dcc.Dropdown(
                                id='bar-stacked-date-range',
                                style=dict(width='150px'),
                                clearable=False,
                                options=[
                                    dict(label='Last week', value=7),
                                    dict(label='Last month', value=30),
                                    dict(label='Last quarter', value=90),
                                    dict(label='Last semester', value=180),
                                    dict(label='Last year', value=360)
                                ],
                                value=30
                            )
                        ]
                    ),

                    dcc.Graph(
                        id='bar-stacked',
                        figure=bar_stacked_fig
                    )
                ]
            )
        ]
    ),

    html.Div(
        className="row",
        children=[
            html.Div(
                className='col-6',
                children=[

                    dcc.Graph(
                        id='pie'
                    ),

                    dcc.RangeSlider(
                        id='pie-range-slider',
                        className="col-6 mx-auto",
                        min=0,
                        max=4,
                        step=None,
                        marks={
                            0: '6 M',
                            1: '3 M',
                            2: '1 M',
                            3: '1 W',
                            4: 'Today'
                        },
                        value=[3, 4]
                    )
                ]
            ),

            html.Div(
                className="col-6 d-flex flex-column justify-content-center \
                           align-self-center align-items-center",
                children=[
                    html.Div(
                        className=f"c100 p{int(exercise_percentage)}",
                        children=[
                            html.Span(
                                id='exercise-percentage',
                                children=[
                                    f"{np.round(exercise_percentage, 1)}%"
                                ]
                            ),
                            html.Div(
                                className="slice",
                                children=[
                                    html.Div(
                                        className="bar"
                                    ),
                                    html.Div(
                                        className="fill"
                                    )
                                ]
                            )
                        ]
                    ),
                    html.H4(
                        "achieved of weekly exercise goal.",
                        className="mb-3"
                    ),

                    html.Div(
                        className=f"c100 p{int(meditation_percentage)}",
                        children=[
                            html.Span(
                                id='meditation-percentage',
                                children=[
                                    f"{np.round(meditation_percentage, 1)}%"
                                ]
                            ),
                            html.Div(
                                className="slice",
                                children=[
                                    html.Div(
                                        className="bar"
                                    ),
                                    html.Div(
                                        className="fill"
                                    )
                                ]
                            )
                        ]
                    ),
                    html.H4(
                        "achieved of weekly meditation goal."
                    )
                ]
            )
        ]
    ),
])


# ====================================================================
# CALLBACKS
# ====================================================================


@app.callback(
    Output('bar-stacked', 'figure'),
    [Input('bar-stacked-date-range', 'value')],
)
def update_date_range(date_range):

    today = dt.date.today()
    start = today - dt.timedelta(days=date_range)

    bar_stacked_fig.update_layout(
        xaxis=dict(range=(start, today + dt.timedelta(days=1))),
        legend=dict(
            x=0, y=1.0,
            bgcolor='rgba(255, 255, 255, 0)',
            bordercolor='rgba(255, 255, 255, 0)'),
    )

    return bar_stacked_fig


@app.callback(
    Output('pie', 'figure'),
    [Input('pie-range-slider', 'value')],
)
def update_range_slider(date_range):

    # Map days in past with range slider
    map = [180, 90, 30, 7, 0]

    today = dt.date.today()
    start = today - dt.timedelta(days=map[date_range[0]])
    end = today - dt.timedelta(days=map[date_range[1]])

    ranged = events[(events['date'] > start) & (events['date'] < end)]

    fig = px.pie(
        ranged, values='duration', names='activity',
        title='Activities distribution'
    )

    return fig


@app.callback(
    Output('refresh', 'children'),
    [Input('refresh', 'n_clicks')]
)
def refresh(n):

    if n is None:
        raise PreventUpdate
    
    events = fetch_events()

    return [f'Refresh ({dt.datetime.now()})']

@app.callback(
    Output('quit', 'children'),
    [Input('quit', 'n_clicks')]
)
def shutdown(n):

    if n is None:
        raise PreventUpdate

    flask_shutdown = request.environ.get('werkzeug.server.shutdown')

    if flask_shutdown is None:
        raise RuntimeError('Not running with werkzeug')

    flask_shutdown()

    return ['Close tab']


@app.server.route('/static/<path:path>')
def static_file(path):
    static_folder = os.path.join(os.getcwd(), 'static')
    return send_from_directory(static_folder, path)

# ====================================================================
# RUN APP
# ====================================================================

if __name__ == '__main__':
    app.run_server(debug=True)
