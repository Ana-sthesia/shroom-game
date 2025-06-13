#!/usr/bin/env python3
import warnings
# Suppress deprecation warnings (for example, from modules like imghdr if used indirectly)
warnings.simplefilter("ignore", DeprecationWarning)

import logging
import random
import time
import os
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
from flask import Flask
from dotenv import load_dotenv

# Load environment variables (from a .env file, if present)
load_dotenv()

# --- Flask app for health checking ---
app = Flask(__name__)

@app.route("/")
def health():
    return "Shroom Game is running", 200

def run_http_server():
    # Render expects the PORT variable; default to 8080 if not defined.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Game Settings ---
BOARD_SIZE = 10               # 10x10 board grid
ROUND_DURATION = 60           # Each round lasts 60 seconds
MAX_MUSHROOMS = 5             # Maximum mushrooms allowed on board

# Global dictionary to store game states by chat ID.
game_states = {}

def render_board(state):
    """
    Render an ASCII game board using emojis.
    Player: 🙂, Raven: 🐦, Mushrooms: 🍄, Empty cells: ⬜.
    Also append game stats and reminder of remaining time.
    """
    board = [['⬜' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    for (x, y) in state['mushrooms']:
        board[y][x] = '🍄'
    rx, ry = state['raven_pos']
    board[ry][rx] = '🐦'
    px, py = state['player_pos']
    board[py][px] = '🙂'
    board_lines = ["".join(row) for row in board]
    time_left = max(0, int(state['start_time'] + ROUND_DURATION - time.time()))
    stats = f"Level: {state['level']}  Score: {state['score']}  Collected: {state['collected']}/{state['required']}\nTime Left: {time_left}s"
    return "\n".join(board_lines) + "\n" + stats

def init_game(chat_id):
    """
    Initialize a new game state for the given chat.
    """
    state = {
        'level': 1,
        'score': 0,
        'collected': 0,
        'required': 3,  # Initially, 3 mushrooms are needed to level up.
        'player_pos': (0, 0),
        'raven_pos': (BOARD_SIZE - 1, BOARD_SIZE - 1),
        'mushrooms': [],
        'start_time': time.time()
    }
    for _ in range(3):
        spawn_mushroom(state)
    game_states[chat_id] = state

def spawn_mushroom(state):
    """
    Spawn a new mushroom at a random free location.
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
    Move the raven one step toward the nearest mushroom, or randomly if none exist.
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
    Update the game state based on the player's move and return the updated board or a game-over message.
    """
    state = game_states.get(chat_id)
    if not state:
        return "Game not started. Use /start to begin."

    # Check round timer.
    time_left = state['start_time'] + ROUND_DURATION - time.time()
    if time_left <= 0:
        msg = "Time's up! "
        if state['collected'] >= state['required']:
            # Level up.
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

    # Update player's position.
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

    # Check for collection.
    if new_pos in state['mushrooms']:
        state['mushrooms'].remove(new_pos)
        state['score'] += 10
        state['collected'] += 1

    # Move the raven.
    move_raven(state)
    if state['player_pos'] == state['raven_pos']:
        msg = "Oh no! The raven caught you. Game over!"
        del game_states[chat_id]
        return msg

    # Random chance to spawn a new mushroom.
    if random.random() < 0.3:
        spawn_mushroom(state)

    return render_board(state)

def get_move_keyboard():
    """
    Return an inline keyboard for directional moves.
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
    Handler for the /start command: initialize the game and display the board.
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
    Process move commands via inline keyboard buttons.
    """
    query = update.callback_query
    chat_id = query.message.chat_id
    move_direction = query.data
    new_state_text = update_game_state(chat_id, move_direction)
    query.edit_message_text(text=new_state_text, reply_markup=get_move_keyboard())

def main():
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    # Start the Flask server for health checks in a background thread.
    threading.Thread(target=run_http_server, daemon=True).start()

    # Set up the Telegram bot.
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_game))
    dp.add_handler(CallbackQueryHandler(move_handler))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()