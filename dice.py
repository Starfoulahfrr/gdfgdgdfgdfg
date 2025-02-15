import logging
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from utils import db, is_admin

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Stockage des paris en cours {chat_id: {message_id: game}}
dice_games = {}

class DiceGame:
    def __init__(self, host_id, host_name, bet_amount, message_id):
        self.host_id = host_id
        self.host_name = host_name
        self.bet_amount = bet_amount
        self.message_id = message_id
        self.status = 'waiting'

async def dice_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Vérifier si l'utilisateur a déjà un pari en cours comme hôte
    for games in dice_games.values():
        for game in games.values():
            if game.host_id == user.id and game.status == 'waiting':
                await update.message.reply_text(
                    "❌ Vous avez déjà un pari en cours!\n"
                    "Attendez qu'il soit terminé ou annulez-le."
                )
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

    game_message = (
        f"🎲 *NOUVEAU PARI* 🎲\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Créateur: {user.first_name}\n"
        f"💰 Mise: {bet_amount} coins\n"
        f"🎯 Gain potentiel: {bet_amount * 2} coins\n"
        f"⏳ Expire dans: 5 minutes"
    )

    keyboard = [[
        InlineKeyboardButton("✅ Participer", callback_data=f"join"),
        InlineKeyboardButton("❌ Annuler", callback_data="cancel")
    ]]

    sent_message = await context.bot.send_message(
        chat_id=chat_id,
        text=game_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

    if chat_id not in dice_games:
        dice_games[chat_id] = {}

    dice_games[chat_id][sent_message.message_id] = DiceGame(
        user.id, user.first_name, bet_amount, sent_message.message_id
    )

    asyncio.create_task(check_game_expiration(context, chat_id, sent_message.message_id))

async def check_game_expiration(context, chat_id, message_id):
    await asyncio.sleep(300)  # 5 minutes
    if chat_id in dice_games and message_id in dice_games[chat_id]:
        game = dice_games[chat_id][message_id]
        if game.status == 'waiting':
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="⏰ *Le pari a expiré*\nAucun joueur n'a rejoint à temps.",
                    parse_mode=ParseMode.MARKDOWN
                )
                del dice_games[chat_id][message_id]
                if not dice_games[chat_id]:
                    del dice_games[chat_id]
            except Exception as e:
                logger.error(f"Erreur lors de l'expiration du jeu: {e}")

async def dice_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    print(f"DEBUG - callback data: {query.data}")
    print(f"DEBUG - chat_id: {chat_id}")
    print(f"DEBUG - message_id: {message_id}")
    print(f"DEBUG - dice_games: {dice_games}")

    await query.answer()

    if chat_id not in dice_games or message_id not in dice_games[chat_id]:
        await query.message.edit_text("❌ Ce pari n'existe plus!")
        return

    game = dice_games[chat_id][message_id]

    if query.data == "join":
        if game.status != 'waiting':
            await query.message.edit_text("❌ Ce pari n'est plus disponible!")
            return

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

        game.status = 'finished'

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

        # Nettoyer le jeu terminé
        del dice_games[chat_id][message_id]
        if not dice_games[chat_id]:
            del dice_games[chat_id]

    elif query.data == "cancel":
        if user.id == game.host_id or is_admin(user.id):
            del dice_games[chat_id][message_id]
            if not dice_games[chat_id]:
                del dice_games[chat_id]
            await query.message.edit_text("❌ Pari annulé", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.answer("❌ Seul le créateur peut annuler le pari!")

def register_dice_handlers(application):
    """Enregistre les handlers pour le jeu de dés"""
    application.add_handler(CommandHandler("dice", dice_start))
    application.add_handler(CallbackQueryHandler(dice_button_handler, pattern="^(join|cancel)$"))
