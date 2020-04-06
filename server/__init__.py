"""Flask server for Codenames"""
# pylint: disable=C0103

import eventlet
import logging
import json
import os
import gc
from sys import getsizeof
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, join_room, leave_room, send, emit
from datetime import datetime, timedelta
from functools import reduce
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from dotenv import load_dotenv
load_dotenv()

# attempt a relative import
try:
    from .codenames import game
except (ImportError, ValueError):
    from codenames import game

# init sentry
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration()]
    )

app = Flask(__name__)
socketio = SocketIO(app)
app.secret_key = os.getenv("SECRET_KEY", "")

# set up logging
if not app.debug:
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

ROOMS = {}

def delete_room(gid):
    del ROOMS[gid]

def is_stale(room):
    """Stale rooms are older than 6 hours, or have gone 20 minutes less than 5 minutes of total playtime"""
    return (((datetime.now() - room.date_modified).total_seconds() >= (60*60*6)) or
        ((datetime.now() - room.date_modified).total_seconds() >= (60*20) and
        room.playtime() <= 5))

def prune():
    """Prune rooms stale for more than 6 hours"""
    if ROOMS:
        rooms = ROOMS.copy()
        for key in rooms.keys():
            if is_stale(ROOMS[key]):
                delete_room(key)
        del rooms
        gc.collect()

@app.route('/debug-sentry')
def trigger_error():
    division_by_zero = 1 / 0

@app.route('/stats')
def stats():
    """display room stats"""
    resp = {
        "total": len(ROOMS.keys()),
        "bytes_used": getsizeof(ROOMS)
    }
    if 'rooms' in request.args:
        if ROOMS:
            resp["rooms"] = sorted([ v.to_json() for v in ROOMS.values() ], key=lambda k: k.get('date_modified'), reverse=True)
        else:
            resp["rooms"] = None
    return jsonify(resp)

@socketio.on('create')
def on_create(data):
    """Create a game lobby"""
    # username = data['username']
    # create the game
    # handle custom wordbanks
    # prune old rooms
    prune()
    if data['dictionaryOptions']['useCustom']:
        gm = game.Info(
            size=data['size'],
            teams=data['teams'],
            wordbank=data['dictionaryOptions']['customWordbank'])
    # dict mixer
    elif data['dictionaryOptions']['mix']:
        gm = game.Info(
            size=data['size'],
            teams=data['teams'],
            mix=data['dictionaryOptions']['mixPercentages'],
            dictionaries=DICTIONARIES)

    # handle standard single dictionary
    else:
        gm = game.Info(
            size=data['size'],
            teams=data['teams'],
            dictionary=data['dictionaryOptions']['dictionaries'],
            dictionaries=DICTIONARIES)

    room = gm.game_id
    ROOMS[room] = gm
    join_room(room)
    # rooms[room].add_player(username)
    emit('join_room', {'room': room})

@socketio.on('join')
def on_join(data):
    """Join a game lobby"""
    # username = data['username']
    room = data['room']
    if room in ROOMS:
        # add player and rebroadcast game object
        # rooms[room].add_player(username)
        join_room(room)
        send(ROOMS[room].to_json(), room=room)
    else:
        emit('error', {'error': 'Unable to join room. Room does not exist.'})

@socketio.on('leave')
def on_leave(data):
    """Leave the game lobby"""
    # username = data['username']
    room = data['room']
    # add player and rebroadcast game object
    # rooms[room].remove_player(username)
    leave_room(room)
    send(ROOMS[room].to_json(), room=room)

@socketio.on('flip_card')
def on_flip_card(data):
    """flip card and rebroadcast game object"""
    ROOMS[data['room']].flip_card(data['card'])
    send(ROOMS[data['room']].to_json(), room=data['room'])

@socketio.on('regenerate')
def on_regenerate(data):
    """regenerate the words list"""
    room = data['room']
    ROOMS[room].generate_board(data.get('newGame', False))
    send(ROOMS[room].to_json(), room=room)

@socketio.on('list_dictionaries')
def list_dictionaries():
    """send a list of dictionary names"""
    # send dict list to client
    emit('list_dictionaries', {'dictionaries': list(DICTIONARIES.keys())})

def __load_dictionaries():
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    FILE_ROOT = os.path.join(APP_ROOT, 'dictionaries')

    DICTIONARIES = {}
    DICTIONARIES["English"] =                   FILE_ROOT + "/english.txt"
    DICTIONARIES["Czech"] =                     FILE_ROOT + "/czech.txt"
    DICTIONARIES["French"] =                    FILE_ROOT + "/french.txt"
    DICTIONARIES["German"] =                    FILE_ROOT + "/german.txt"
    DICTIONARIES["Greek"] =                     FILE_ROOT + "/greek.txt"
    DICTIONARIES["Italian"] =                   FILE_ROOT + "/italian.txt"
    DICTIONARIES["Portuguese"] =                FILE_ROOT + "/portuguese.txt"
    DICTIONARIES["Russian"] =                   FILE_ROOT + "/russian.txt"
    DICTIONARIES["Spanish"] =                   FILE_ROOT + "/spanish.txt"
    DICTIONARIES["Cards Against Humanity"] =    FILE_ROOT + "/cards_against_humanity.txt"
    def load_dictionary(path):
        with open(path, 'r') as words_file:
            return [elem for elem in words_file.read().split('\n') if len(elem.strip()) > 0]
    return {k: load_dictionary(v) for k,v in DICTIONARIES.items()}

if __name__ == '__main__':
    global DICTIONARIES
    DICTIONARIES = __load_dictionaries()
    socketio.run(app, host='0.0.0.0', debug=True)
