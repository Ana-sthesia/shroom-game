#!/usr/bin/env python3
import logging
import random
import time
import os
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from flask import Flask

# --- Set up a simple Flask app for health checks ---
app = Flask(__name__)

@app.route("/")
def health():
    return "Shroom Game is running", 200

def run_http_server():
    # Koyeb sets the PORT environment variable; default to 8080 if not set.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Game Settings ---
BOARD_SIZE = 10               # Board is 10x10
ROUND_DURATION = 60           # Each round lasts 60 seconds
MAX_MUSHROOMS = 5             # Maximum number of mushrooms on board

# Global dictionary to store game states per chat
game_states = {}

def render_board(state):
    """
    Render the game board as an ASCII grid using emojis.
    Player is represented as 🙂, Raven as 🐦, Mushrooms as 🍄, Empty cells as ⬜.
    """
    board = [['⬜' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    # Place mushrooms
    for (x, y) in state['mushrooms']:
        board[y][x] = '🍄'
    # Place raven
    rx, ry = state['raven_pos']
    board[ry][rx] = '🐦'
    # Place player (overwrites anything underneath)
    px, py = state['player_pos']
    board[py][px] = '🙂'
    board_lines = ["".join(row) for row in board]
    board_text = "\n".join(board_lines)
    # Add stats and remaining round time
    time_left = max(0, int(state['start_time'] + ROUND_DURATION - time.time()))
    stats = f"Level: {state['level']}  Score: {state['score']}  Collected: {state['collected']}/{state['required']}\nTime Left: {time_left}s"
    return board_text + "\n" + stats

def init_game(chat_id):
    """
    Initialize a new game state for a given chat.
    """
    state = {
        'level': 1,
        'score': 0,
        'collected': 0,
        'required': 3,  # Level 1: need 3 mushrooms to level up
        'player_pos': (0, 0),
        'raven_pos': (BOARD_SIZE - 1, BOARD_SIZE - 1),
        'mushrooms': [],
        'start_time': time.time()
    }
    # Spawn 3 initial mushrooms
    for _ in range(3):
        spawn_mushroom(state)
    game_states[chat_id] = state

def spawn_mushroom(state):
    """
    Add a new mushroom at a random location not already occupied.
    """
    if len(state['mushrooms']) >= MAX_MUSHROOMS:
        return
    while True:
        x = random.randint(0, BOARD_SIZE - 1)
        y = random.randint(0, BOARD_SIZE - 1)
        if (x, y) == state['player_pos'] or (x, y) == state['raven_pos'] or (x, y) in state['mushrooms']:
            continue
        state['mushrooms'].append((x, y))
        break

def move_raven(state):
    """
    Move the raven one step toward the nearest mushroom or randomly if none exists.
    """
    rx, ry = state['raven_pos']
    if state['mushrooms']:
        target = min(state['mushrooms'], key=lambda pos: abs(pos[0]-rx) + abs(pos[1]-ry))
        dx = 1 if target[0] > rx else -1 if target[0] < rx else 0
        dy = 1 if target[1] > ry else -1 if target[1] < ry else 0
        new_raven = (rx + dx, ry + dy)
    else:
        possible_moves = []
        if rx > 0: possible_moves.append((-1, 0))
        if rx < BOARD_SIZE - 1: possible_moves.append((1, 0))
        if ry > 0: possible_moves.append((0, -1))
        if ry < BOARD_SIZE - 1: possible_moves.append((0, 1))
        if possible_moves:
            dx, dy = random.choice(possible_moves)
            new_raven = (rx + dx, ry + dy)
        else:
            new_raven = (rx, ry)
    state['raven_pos'] = new_raven

def update_game_state(chat_id, move_direction):
    """
    Process player movement and update the game state accordingly.
    """
    state = game_states.get(chat_id)
    if not state:
        return "Game not started. Use /start to begin."

    # Check if the round time has expired.
    time_left = state['start_time'] + ROUND_DURATION - time.time()
    if time_left <= 0:
        msg = "Time's up! "
        if state['collected'] >= state['required']:
            # Level up
            state['level'] += 1
            state['required'] += 2
            msg += f"You progressed to level {state['level']}!"
            state['collected'] = 0
            state['player_pos'] = (0, 0)
            state['raven_pos'] = (BOARD_SIZE - 1, BOARD_SIZE - 1)
            state['mushrooms'] = []
            for _ in range(3):
                spawn_mushroom(state)
            state['start_time'] = time.time()
        else:
            msg += "Game over! You didn't collect enough mushrooms."
            del game_states[chat_id]
            return msg
        return msg

    # Update player's position based on input move.
    px, py = state['player_pos']
    if move_direction == 'up':
        new_pos = (px, max(py - 1, 0))
    elif move_direction == 'down':
        new_pos = (px, min(py + 1, BOARD_SIZE - 1))
    elif move_direction == 'left':
        new_pos = (max(px - 1, 0), py)
    elif move_direction == 'right':
        new_pos = (min(px + 1, BOARD_SIZE - 1), py)
    else:
        new_pos = (px, py)
    state['player_pos'] = new_pos

    # Check for mushroom collection
    if new_pos in state['mushrooms']:
        state['mushrooms'].remove(new_pos)
        state['score'] += 10
        state['collected'] += 1

    # Move the raven and check for collision
    move_raven(state)
    if state['player_pos'] == state['raven_pos']:
        msg = "Oh no! The raven caught you. Game over!"
        del game_states[chat_id]
        return msg

    # Randomly spawn a new mushroom with a 30% chance
    if random.random() < 0.3:
        spawn_mushroom(state)
    
    return render_board(state)

def get_move_keyboard():
    """
    Return an inline keyboard for move directions.
    """
    keyboard = [
        [InlineKeyboardButton("Up", callback_data="up")],
        [InlineKeyboardButton("Left", callback_data="left"),
         InlineKeyboardButton("Right", callback_data="right")],
        [InlineKeyboardButton("Down", callback_data="down")]
    ]
    return InlineKeyboardMarkup(keyboard)

def start_game(update: Update, context: CallbackContext):
    """
    Handler for the /start command: initialize the game and send the initial board.
    """
    chat_id = update.effective_chat.id
    init_game(chat_id)
    state = game_states[chat_id]
    welcome_text = (
        "Welcome to Mushroom Maniac!\n"
        "Move around and eat as many mushrooms (🍄) as you can while avoiding the raven (🐦)!\n"
        "Each round lasts 1 minute. When you collect enough mushrooms, you'll level up.\n"
        "Use the buttons below to move."
    )
    board_text = render_board(state)
    update.message.reply_text(welcome_text + "\n\n" + board_text, reply_markup=get_move_keyboard())

def move_handler(update: Update, context: CallbackContext):
    """
    Handler for move commands via inline keyboard buttons.
    """
    query = update.callback_query

