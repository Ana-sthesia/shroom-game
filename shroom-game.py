#!/usr/bin/env python3
import warnings
warnings.simplefilter("ignore", DeprecationWarning)

import json
import os
import time
import random
import logging
import threading
from flask import Flask
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# Load environment variables
load_dotenv()

# --- Flask for Health Checks ---
app = Flask(__name__)

@app.route("/")
def health():
    return "Shroom Game is running", 200

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Game Settings ---
BOARD_SIZE = 10
ROUND_DURATION = 60
MAX_MUSHROOMS = 5
LEADERBOARD_FILE = "leaderboard.json"

# Global state storage
game_states = {}

# --- Leaderboard Functions ---
def load_leaderboard():
    """Load leaderboard data from JSON."""
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as file:
            return json.load(file)
    return {}

def save_leaderboard(leaderboard):
    """Save leaderboard data to JSON."""
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(leaderboard, file, indent=4)

def update_leaderboard(user_id, username, score):
    """Update leaderboard with player's score."""
    leaderboard = load_leaderboard()
    if user_id not in leaderboard or score > leaderboard[user_id]["score"]:
        leaderboard[user_id] = {"username": username, "score": score}
        save_leaderboard(leaderboard)

def get_leaderboard_text():
    """Generate a formatted leaderboard message."""
    leaderboard = load_leaderboard()
    sorted_players = sorted(leaderboard.items(), key=lambda x: x[1]["score"], reverse=True)
    if not sorted_players:
        return "No scores yet! Be the first to climb the ranks."

    text = "**🏆 Leaderboard 🏆**\n"
    for rank, (user_id, data) in enumerate(sorted_players, start=1):
        text += f"{rank}. {data['username']} - {data['score']} points\n"
    return text

# --- Game Functions ---
def init_game(chat_id, username):
    """Initialize a new game state for the given chat."""
    state = {
        'level': 1,
        'score': 0,
        'collected': 0,
        'required': 3,
        'player_pos': (0, 0),
        'raven_pos': (BOARD_SIZE - 1, BOARD_SIZE - 1),
        'mushrooms': [],
        'start_time': time.time(),
        'user_id': chat_id,
        'username': username
    }
    for _ in range(3):
        spawn_mushroom(state)
    game_states[chat_id] = state

def render_board(state):
    """Create a visual representation of the game board."""
    board = [['⬜' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    for (x, y) in state['mushrooms']:
        board[y][x] = '🍄'
    rx, ry = state['raven_pos']
    board[ry][rx] = '🐦'
    px, py = state['player_pos']
    board[py][px] = '🙂'
    time_left = max(0, int(state['start_time'] + ROUND_DURATION - time.time()))
    stats = f"Level: {state['level']}  Score: {state['score']}  Collected: {state['collected']}/{state['required']}\nTime Left: {time_left}s"
    return "\n".join(["".join(row) for row in board]) + "\n" + stats

def spawn_mushroom(state):
    """Generate a new mushroom at a random location."""
    if len(state['mushrooms']) >= MAX_MUSHROOMS:
        return
    while True:
        x, y = random.randint(0, BOARD_SIZE - 1), random.randint(0, BOARD_SIZE - 1)
        if (x, y) in [state['player_pos'], state['raven_pos']] or (x, y) in state['mushrooms']:
            continue
        state['mushrooms'].append((x, y))
        break

def move_raven(state):
    """Move the raven closer to the nearest mushroom."""
    rx, ry = state['raven_pos']
    if state['mushrooms']:
        target = min(state['mushrooms'], key=lambda pos: abs(pos[0]-rx) + abs(pos[1]-ry))
        dx, dy = (1 if target[0] > rx else -1 if target[0] < rx else 0), (1 if target[1] > ry else -1 if target[1] < ry else 0)
        state['raven_pos'] = (rx + dx, ry + dy)

def update_game_state(chat_id, move_direction):
    """Update the game state based on player's move."""
    state = game_states.get(chat_id)
    if not state:
        return "Game not started. Use /start to begin."

    time_left = state['start_time'] + ROUND_DURATION - time.time()
    if time_left <= 0:
        update_leaderboard(state['user_id'], state['username'], state['score'])
        msg = f"Time's up! You scored {state['score']} points.\n"
        del game_states[chat_id]
        return msg + "Use /leaderboard to view rankings."

    px, py = state['player_pos']
    new_pos = {
        'up': (px, max(py - 1, 0)),
        'down': (px, min(py + 1, BOARD_SIZE - 1)),
        'left': (max(px - 1, 0), py),
        'right': (min(px + 1, BOARD_SIZE - 1), py)
    }.get(move_direction, (px, py))
    
    state['player_pos'] = new_pos
    if new_pos in state['mushrooms']:
        state['mushrooms'].remove(new_pos)
        state['score'] += 10
        state['collected'] += 1

    move_raven(state)
    if state['player_pos'] == state['raven_pos']:
        update_leaderboard(state['user_id'], state['username'], state['score'])
        del game_states[chat_id]
        return "Oh no! The raven caught you. Game over!\nUse /leaderboard to view rankings."

    return render_board(state)

# --- Telegram Handlers ---
def start_game(update: Update, context: CallbackContext):
    """Start a new game."""
    chat_id = update.effective_chat.id
    username = update.effective_chat.username or f"Player {chat_id}"
    init_game(chat_id, username)
    state = game_states[chat_id]
    update.message.reply_text(render_board(state), reply_markup=get_move_keyboard())

def leaderboard(update: Update, context: CallbackContext):
    """Display the leaderboard."""
    update.message.reply_text(get_leaderboard_text())

def move_handler(update: Update, context: CallbackContext):
    """Handle movement buttons."""
    query = update.callback_query
    chat_id = query.message.chat_id
    move_direction = query.data
    query.edit_message_text(text=update_game_state(chat_id, move_direction), reply_markup=get_move_keyboard())

def get_move_keyboard():
    """Create inline keyboard for movement."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Up", callback_data="up")],
        [InlineKeyboardButton("Left", callback_data="left"), InlineKeyboardButton("Right", callback_data="right")],
        [InlineKeyboardButton("Down", callback_data="down")]
    ])

def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_game))
    dp.add_handler(CommandHandler("leaderboard", leaderboard))
    dp.add_handler(CallbackQueryHandler(move_handler))
    threading.Thread(target=run_http_server, daemon=True).start()
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
