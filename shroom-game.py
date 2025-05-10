#!/usr/bin/env python3
import logging
import random
import time
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# Set up logging for debugging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Game settings
BOARD_SIZE = 10               # Board is 10x10
ROUND_DURATION = 60           # Each round lasts 60 seconds
MAX_MUSHROOMS = 5             # Maximum number of mushrooms on board

# Global dictionary to store game states per chat
# Each state holds: level, score, collected mushroom count, requirement to level up,
# player position, raven position, mushroom positions, start time.
game_states = {}

def render_board(state):
    """
    Render the game board as an ASCII grid using emojis.
    Player is represented as 🙂
    Raven is represented as 🐦
    Mushrooms are represented as 🍄
    Empty cells are represented as ⬜
    """
    # Initialize empty board
    board = [['⬜' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    # Place mushrooms
    for (x, y) in state['mushrooms']:
        board[y][x] = '🍄'
    # Place raven
    rx, ry = state['raven_pos']
    board[ry][rx] = '🐦'
    # Place player (overwrites any cell if overlapping)
    px, py = state['player_pos']
    board[py][px] = '🙂'
    # Combine rows into a string
    board_lines = ["".join(row) for row in board]
    board_text = "\n".join(board_lines)
    # Add game stats
    time_left = max(0, int(state['start_time'] + ROUND_DURATION - time.time()))
    stats = f"Level: {state['level']}  Score: {state['score']}  Collected: {state['collected']}/{state['required']}\nTime Left: {time_left}s"
    return board_text + "\n" + stats

def init_game(chat_id):
    """
    Initialize a new game state for the chat.
    """
    state = {
        'level': 1,
        'score': 0,
        'collected': 0,
        'required': 3,  # Level 1: need 3 mushrooms to progress
        'player_pos': (0, 0),  # Start in the top-left corner
        'raven_pos': (BOARD_SIZE - 1, BOARD_SIZE - 1),  # Raven starts at bottom-right
        'mushrooms': [],
        'start_time': time.time()
    }
    # Spawn a few initial mushrooms
    for _ in range(3):
        spawn_mushroom(state)
    game_states[chat_id] = state

def spawn_mushroom(state):
    """
    Add a new mushroom at a random location that is not already occupied.
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
    Move the raven one step toward the nearest mushroom.
    If no mushrooms are present, move randomly.
    """
    rx, ry = state['raven_pos']
    if state['mushrooms']:
        # Find the nearest mushroom (using Manhattan distance)
        target = min(state['mushrooms'], key=lambda pos: abs(pos[0] - rx) + abs(pos[1] - ry))
        dx = 1 if target[0] > rx else -1 if target[0] < rx else 0
        dy = 1 if target[1] > ry else -1 if target[1] < ry else 0
        new_raven = (rx + dx, ry + dy)
    else:
        # Move randomly if there is no target
        possible_moves = []
        if rx > 0:
            possible_moves.append((-1, 0))
        if rx < BOARD_SIZE - 1:
            possible_moves.append((1, 0))
        if ry > 0:
            possible_moves.append((0, -1))
        if ry < BOARD_SIZE - 1:
            possible_moves.append((0, 1))
        if possible_moves:
            dx, dy = random.choice(possible_moves)
            new_raven = (rx + dx, ry + dy)
        else:
            new_raven = (rx, ry)
    state['raven_pos'] = new_raven

def update_game_state(chat_id, move_direction):
    """
    Process a player's move and update the game state.
    Returns a message string (the updated board or game over message).
    """
    state = game_states.get(chat_id)
    if not state:
        return "Game not started. Use /start to begin."

    # Check if the round has expired
    time_left = state['start_time'] + ROUND_DURATION - time.time()
    if time_left <= 0:
        msg = "Time's up! "
        if state['collected'] >= state['required']:
            # Advance to next level:
            state['level'] += 1
            state['required'] += 2  # Increase mushrooms required next level
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

    # Update player's position based on input
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

    # If player lands on a mushroom, collect it.
    if new_pos in state['mushrooms']:
        state['mushrooms'].remove(new_pos)
        state['score'] += 10
        state['collected'] += 1

    # Move the raven after the player
    move_raven(state)

    # Check for collision with the raven
    if state['player_pos'] == state['raven_pos']:
        msg = "Oh no! The raven caught you. Game over!"
        del game_states[chat_id]
        return msg

    # With a chance, spawn a new mushroom
    if random.random() < 0.3:
        spawn_mushroom(state)

    return render_board(state)

def get_move_keyboard():
    """
    Create an inline keyboard with move options.
    """
    keyboard = [
        [InlineKeyboardButton("Up", callback_data='up')],
        [InlineKeyboardButton("Left", callback_data='left'),
         InlineKeyboardButton("Right", callback_data='right')],
        [InlineKeyboardButton("Down", callback_data='down')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Telegram Command Handlers

def start_game(update: Update, context: CallbackContext):
    """
    Handler for the /start command: Initialize the game and show the board.
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
    Process movement commands via inline keyboard button presses.
    """
    query = update.callback_query
    chat_id = query.message.chat_id
    move_direction = query.data  # Expected: 'up', 'down', 'left', 'right'
    new_state_text = update_game_state(chat_id, move_direction)
    query.edit_message_text(text=new_state_text, reply_markup=get_move_keyboard())

def main():
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Add command and callback query handlers
    dp.add_handler(CommandHandler("start", start_game))
    dp.add_handler(CallbackQueryHandler(move_handler))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
