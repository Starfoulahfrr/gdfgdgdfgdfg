import logging
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from utils import db, is_admin

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Un simple dictionnaire pour stocker les jeux actifs par chat_id
active_games = {}

class DiceGame:
    def __init__(self, host_id, host_name, bet_amount):
        self.host_id = host_id
        self.host_name = host_name
        self.bet_amount = bet_amount
        self.opponent_id = None
        self.opponent_name = None
        self.status = 'waiting'

async def dice_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Démarre un nouveau pari de dés"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id in active_games:
        await update.message.reply_text("❌ Un pari est déjà en cours dans ce chat!")
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
    active_games[chat_id] = game

    game_message = (
        f"🎲 *NOUVEAU PARI* 🎲\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Créateur: {user.first_name}\n"
        f"💰 Mise: {bet_amount} coins\n"
        f"🎯 Gain potentiel: {bet_amount * 2} coins\n"
        f"⏳ Expire dans: 5 minutes"
    )

    keyboard = [[
        InlineKeyboardButton("✅ Participer", callback_data="join"),
        InlineKeyboardButton("❌ Annuler", callback_data="cancel")
    ]]

    await context.bot.send_message(
        chat_id=chat_id,
        text=game_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

    # Programmer l'expiration
    asyncio.create_task(check_game_expiration(context, chat_id))

async def check_game_expiration(context, chat_id):
    """Vérifie l'expiration du jeu après 5 minutes"""
    await asyncio.sleep(300)
    if chat_id in active_games:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏰ *Le pari a expiré*\nAucun joueur n'a rejoint à temps.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'expiration du jeu: {e}")
        del active_games[chat_id]

async def dice_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les interactions avec les boutons"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id

    # Important: Toujours répondre au callback query
    await query.answer()

    # Vérifier si un jeu existe dans ce chat
    if chat_id not in active_games:
        await query.message.edit_text("❌ Ce pari n'existe plus!")
        return

    game = active_games[chat_id]

    if query.data == "join":
        if game.status != 'waiting':
            await query.message.reply_text("❌ Ce pari n'est plus disponible!")
            return

        if user.id == game.host_id:
            await query.message.reply_text("❌ Vous ne pouvez pas rejoindre votre propre pari!")
            return

        balance = db.get_balance(user.id)
        if balance < game.bet_amount:
            await query.message.reply_text(
                f"❌ Solde insuffisant!\n"
                f"Votre solde: {balance} coins"
            )
            return

        # Rejoindre le jeu
        game.opponent_id = user.id
        game.opponent_name = user.first_name
        game.status = 'playing'

        # Déterminer le gagnant
        is_pile = random.choice([True, False])
        is_host_winner = random.choice([True, False])

        if is_host_winner:
            winner_id = game.host_id
            winner_name = game.host_name
            loser_id = game.opponent_id
            loser_name = game.opponent_name
        else:
            winner_id = game.opponent_id
            winner_name = game.opponent_name
            loser_id = game.host_id
            loser_name = game.host_name

        # Mettre à jour les soldes
        db.update_game_result(winner_id, game.bet_amount, 'win')
        db.update_game_result(loser_id, game.bet_amount, 'lose')

        # Obtenir les nouveaux soldes
        winner_balance = db.get_balance(winner_id)
        loser_balance = db.get_balance(loser_id)

        result_message = (
            f"🎲 *RÉSULTAT DU PARI* 🎲\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{'🦅 PILE!' if is_pile else '👾 FACE!'}\n\n"
            f"*GAGNANT* 🏆\n"
            f"{winner_name} (+{game.bet_amount} coins)\n"
            f"💰 Nouveau solde: {winner_balance} coins\n\n"
            f"*PERDANT* 💀\n"
            f"{loser_name} (-{game.bet_amount} coins)\n"
            f"💰 Nouveau solde: {loser_balance} coins\n\n"
            f"La chance tournera peut-être la prochaine fois!"
        )

        await query.message.edit_text(
            text=result_message,
            parse_mode=ParseMode.MARKDOWN
        )

        # Supprimer le jeu
        del active_games[chat_id]

    elif query.data == "cancel":
        if user.id == game.host_id or is_admin(user.id):
            del active_games[chat_id]
            await query.message.edit_text(
                "❌ Pari annulé",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.answer("❌ Seul le créateur peut annuler le pari!")

def register_dice_handlers(application):
    """Enregistre les handlers pour le jeu de dés"""
    application.add_handler(CommandHandler("dice", dice_start))
    application.add_handler(CallbackQueryHandler(dice_button_handler))