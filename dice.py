import logging
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes
from telegram.constants import ParseMode
from utils import db, is_admin

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Utilise la même variable que le main.py
active_games = {}

class DiceGame:
    def __init__(self, host_id, host_name, bet_amount):
        self.host_id = host_id
        self.host_name = host_name
        self.bet_amount = bet_amount
        self.game_type = 'dice'

async def dice_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Vérifier si l'utilisateur a déjà un pari en cours
    for chat_games in active_games.values():
        for game in chat_games.values():
            if hasattr(game, 'game_type') and game.game_type == 'dice' and game.host_id == user.id:
                await update.message.reply_text("❌ Vous avez déjà un pari en cours!")
                return

    try:
        bet_amount = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ Veuillez spécifier une mise valide.\n"
            "Usage: `/dice [mise]`\n"
            "Exemple: `/dice 100`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if bet_amount < 10 or bet_amount > 1000000:
        await update.message.reply_text("❌ La mise doit être entre 10 et 1000000 coins.")
        return

    balance = db.get_balance(user.id)
    if balance < bet_amount:
        await update.message.reply_text(
            f"❌ Solde insuffisant!\n"
            f"Votre solde: {balance} coins"
        )
        return

    game = DiceGame(user.id, user.first_name, bet_amount)

    keyboard = [[
        InlineKeyboardButton("✅ Participer", callback_data="join"),
        InlineKeyboardButton("❌ Annuler", callback_data="cancel")
    ]]

    message = await update.message.reply_text(
        f"🎲 *NOUVEAU PARI* 🎲\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Créateur: {user.first_name}\n"
        f"💰 Mise: {bet_amount} coins\n"
        f"🎯 Gain potentiel: {bet_amount * 2} coins\n"
        f"⏳ Expire dans: 5 minutes",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

    if chat_id not in active_games:
        active_games[chat_id] = {}
    active_games[chat_id][message.message_id] = game

async def check_game_expiration(context, chat_id, message_id):
    await asyncio.sleep(300)  # 5 minutes
    if chat_id in active_games and message_id in active_games[chat_id]:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⏰ *Le pari a expiré*\nAucun joueur n'a rejoint à temps.",
                parse_mode=ParseMode.MARKDOWN
            )
            del active_games[chat_id][message_id]
            if not active_games[chat_id]:
                del active_games[chat_id]
        except Exception as e:
            logger.error(f"Erreur lors de l'expiration du jeu: {e}")

async def dice_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = update.effective_chat.id
    message_id = query.message.message_id

    if chat_id not in active_games or message_id not in active_games[chat_id]:
        await query.answer()
        await query.message.edit_text("❌ Ce pari n'existe plus!")
        return

    game = active_games[chat_id][message_id]

    if query.data == "join":
        if user.id == game.host_id:
            await query.answer("❌ Vous ne pouvez pas rejoindre votre propre pari!")
            return

        balance = db.get_balance(user.id)
        if balance < game.bet_amount:
            await query.answer(f"❌ Solde insuffisant! (Solde: {balance} coins)")
            return

        # Déterminer le gagnant
        is_pile = random.choice([True, False])
        is_host_winner = random.choice([True, False])

        if is_host_winner:
            winner_id = game.host_id
            winner_name = game.host_name
            loser_id = user.id
            loser_name = user.first_name
        else:
            winner_id = user.id
            winner_name = user.first_name
            loser_id = game.host_id
            loser_name = game.host_name

        # Mettre à jour les soldes
        db.update_game_result(winner_id, game.bet_amount, 'dice_win')
        db.update_game_result(loser_id, game.bet_amount, 'lose')

        # Obtenir les nouveaux soldes
        winner_balance = db.get_balance(winner_id)
        loser_balance = db.get_balance(loser_id)

        await query.message.edit_text(
            f"🎲 *RÉSULTAT DU PARI* 🎲\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{'🦅 PILE!' if is_pile else '👾 FACE!'}\n\n"
            f"*GAGNANT* 🏆\n"
            f"{winner_name} (+{game.bet_amount} coins)\n"
            f"💰 Nouveau solde: {winner_balance} coins\n\n"
            f"*PERDANT* 💀\n"
            f"{loser_name} (-{game.bet_amount} coins)\n"
            f"💰 Nouveau solde: {loser_balance} coins\n\n"
            f"La chance tournera peut-être la prochaine fois!",
            parse_mode=ParseMode.MARKDOWN
        )

        # Nettoyer le jeu
        del active_games[chat_id][message_id]
        if not active_games[chat_id]:
            del active_games[chat_id]

    elif query.data == "cancel":
        if user.id == game.host_id or is_admin(user.id):
            del active_games[chat_id][message_id]
            if not active_games[chat_id]:
                del active_games[chat_id]
            await query.message.edit_text("❌ Pari annulé", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.answer("❌ Seul le créateur peut annuler le pari!")

    await query.answer()

def register_dice_handlers(application):
    application.add_handler(CommandHandler("dice", dice_start))
