import logging
import random
import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from logging.handlers import RotatingFileHandler
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, Defaults

# Configuration du logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

game_logger = logging.getLogger('blackjack')
game_logger.setLevel(logging.DEBUG)

file_handler = RotatingFileHandler(
    'logs/blackjack.log',
    maxBytes=1024*1024,
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
game_logger.addHandler(file_handler)

# Variables globales
ADMIN_USERS = [5277718388, 5909979625]  # Remplacez par vos IDs admin
TOKEN = "77190476"  # Remplacez par votre token
INITIAL_BALANCE = 1500
MAX_PLAYERS = 2000
DAILY_AMOUNT = 1000

# Dictionnaires pour le suivi des parties
active_games: Dict[int, 'MultiPlayerGame'] = {}
waiting_games: Set[int] = set()
game_messages: Dict[int, int] = {}
last_game_message: Dict[int, int] = {}
last_end_game_message: Dict[int, int] = {}
CLASSEMENT_MESSAGE_ID = None
CLASSEMENT_CHAT_ID = None


class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect('blackjack.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.setup_database()
    
    def setup_database(self):
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 1500,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                games_split INTEGER DEFAULT 0,
                total_bets INTEGER DEFAULT 0,
                biggest_win INTEGER DEFAULT 0,
                last_daily DATETIME
            );
            
            CREATE TABLE IF NOT EXISTS game_history (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bet_amount INTEGER,
                result TEXT,
                hand_type TEXT DEFAULT 'normal',
                timestamp DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
            
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                achievement_type TEXT,
                achieved_at DATETIME,
                PRIMARY KEY (user_id, achievement_type),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
        ''')
        self.conn.commit()

    def user_exists(self, user_id: int) -> bool:
        """Vérifie si un utilisateur existe dans la base de données"""
        try:
            self.cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
            return bool(self.cursor.fetchone())
        except Exception as e:
            game_logger.error(f"Error checking user existence: {e}")
            return False

    def register_user(self, user_id: int, username: str) -> bool:
        try:
            self.cursor.execute('''
                INSERT INTO users (
                    user_id, username, balance, games_played,
                    games_won, games_split, total_bets, biggest_win, last_daily
                ) VALUES (?, ?, ?, 0, 0, 0, 0, 0, ?)
            ''', (user_id, username, INITIAL_BALANCE, '2000-01-01 00:00:00'))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def update_game_result(self, user_id: int, bet_amount: int, result: str, hand_type: str = 'normal'):
        multiplier = {
            'win': 2,
            'blackjack': 2.5,
            'lose': 0,
            'push': 1
        }.get(result, 0)
        
        winnings = int(bet_amount * multiplier)
        
        self.cursor.execute('''
            UPDATE users 
            SET balance = balance + ?,
                games_played = games_played + 1,
                games_won = games_won + CASE WHEN ? IN ('win', 'blackjack') THEN 1 ELSE 0 END,
                games_split = games_split + CASE WHEN ? = 'split' THEN 1 ELSE 0 END,
                total_bets = total_bets + ?,
                biggest_win = CASE 
                    WHEN ? > biggest_win AND ? IN ('win', 'blackjack')
                    THEN ? ELSE biggest_win 
                END
            WHERE user_id = ?
        ''', (winnings - bet_amount, result, hand_type, bet_amount, winnings, result, winnings, user_id))
        
        self.cursor.execute('''
            INSERT INTO game_history (user_id, bet_amount, result, hand_type, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, bet_amount, result, hand_type, datetime.utcnow()))
        
        self.conn.commit()

    def get_player_rank(self, balance: int) -> Tuple[str, str, float, Optional[str]]:
        ranks = [
            (0, "🤡 Clodo"),
            (500, "🎲 Petit joueur"),
            (1000, "🎰 Joueur lambda"),
            (2500, "💰 Parieur"),
            (5000, "💎 Parieur Pro"),
            (10000, "🎩 High Roller"),
            (25000, "👑 VIP"),
            (50000, "🌟 VIP Elite"),
            (100000, "🔥 VIP Platine"),
            (250000, "🌈 VIP Diamond"),
            (500000, "⚡ Légende"),
            (1000000, "🌌 Grand Maître")
        ]
        
        current_rank = ranks[0]
        for threshold, rank in ranks:
            if balance >= threshold:
                current_rank = (threshold, rank)
            else:
                break
                
        current_index = ranks.index(current_rank)
        next_rank = ranks[current_index + 1] if current_index < len(ranks) - 1 else None
        
        emoji, title = current_rank[1].split(" ", 1)
        
        if next_rank:
            current_threshold = current_rank[0]
            next_threshold = next_rank[0]
            progress = ((balance - current_threshold) / (next_threshold - current_threshold)) * 100
            progress = min(100, max(0, progress))
        else:
            progress = 100
        
        return emoji, title, progress, next_rank[1] if next_rank else None

    def get_balance(self, user_id: int) -> int:
        self.cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else 0

    def set_balance(self, user_id: int, amount: int) -> None:
        self.cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, user_id))
        self.conn.commit()

    def can_claim_daily(self, user_id: int) -> Tuple[bool, Optional[timedelta]]:
        self.cursor.execute('SELECT last_daily FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if not result or not result[0]:
            return True, None
            
        last_daily = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        now = datetime.utcnow()
        time_diff = now - last_daily
        
        if time_diff.total_seconds() >= 86400:  # 24 heures
            return True, None
        else:
            time_remaining = timedelta(days=1) - time_diff
            return False, time_remaining

    def claim_daily(self, user_id: int) -> bool:
        try:
            self.cursor.execute('''
                UPDATE users 
                SET balance = balance + ?,
                    last_daily = ?
                WHERE user_id = ?
            ''', (DAILY_AMOUNT, datetime.utcnow(), user_id))
            self.conn.commit()
            return True
        except Exception as e:
            game_logger.error(f"Error in claim_daily: {e}")
            return False

    def get_stats(self, user_id: int) -> dict:
        try:
            self.cursor.execute('''
                SELECT balance, games_played, games_won, games_split,
                       total_bets, biggest_win
                FROM users WHERE user_id = ?
            ''', (user_id,))
            result = self.cursor.fetchone()
            
            if result:
                return {
                    'balance': result[0],
                    'games_played': result[1],
                    'games_won': result[2],
                    'games_split': result[3],
                    'total_bets': result[4],
                    'biggest_win': result[5]
                }
            return {
                'balance': 0,
                'games_played': 0,
                'games_won': 0,
                'games_split': 0,
                'total_bets': 0,
                'biggest_win': 0
            }
        except Exception as e:
            game_logger.error(f"Error in get_stats: {e}")
            return {}

    def get_leaderboard(self) -> List[Tuple[str, int]]:
        self.cursor.execute('''
            SELECT username, balance 
            FROM users 
            ORDER BY balance DESC 
            LIMIT 10
        ''')
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()
# Initialiser la base de données
db = DatabaseManager()

class Card:
    def __init__(self, rank: str, suit: str):
        self.rank = rank
        self.suit = suit
        
    def __str__(self) -> str:
        suits = {'♠': '♠️', '♥': '♥️', '♦': '♦️', '♣': '♣️'}
        return f"{self.rank}{suits[self.suit]}"

    def get_value(self) -> List[int]:
        """Retourne les valeurs possibles de la carte"""
        if self.rank in ['J', 'Q', 'K']:
            return [10]
        elif self.rank == 'A':
            return [1, 11]
        else:
            return [int(self.rank)]

class Deck:
    def __init__(self):
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        suits = ['♠', '♥', '♦', '♣']
        self.cards = [Card(rank, suit) for rank in ranks for suit in suits]
        self.shuffle()
    
    def shuffle(self):
        """Mélange le deck"""
        random.shuffle(self.cards)
    
    def deal(self) -> Optional[Card]:
        """Distribue une carte, recrée un deck si vide"""
        if not self.cards:
            self.__init__()
        return self.cards.pop() if self.cards else None

class Hand:
    def __init__(self, bet: int = 0):  # On rend le paramètre bet optionnel avec une valeur par défaut
        self.cards = []
        self.status = 'playing'  # 'playing', 'stand', 'bust', 'blackjack', 'win', 'lose', 'push'
        self.bet = bet
        self.timeout = None

    def __str__(self):
        return ' '.join(str(card) for card in self.cards)

    def add_card(self, card):
        self.cards.append(card)

    def get_value(self) -> int:
        value = 0
        aces = 0
        
        for card in self.cards:
            if card.value == 1:  # As
                aces += 1
            elif card.value > 10:  # Valet, Dame, Roi
                value += 10
            else:
                value += card.value
        
        # Gérer les As (1 ou 11)
        for _ in range(aces):
            if value + 11 <= 21:
                value += 11
            else:
                value += 1
                
        return value
        
class MultiPlayerGame:
    def __init__(self, host_id: int, host_name: str):
        self.host_id = host_id
        self.host_name = host_name
        self.players = {}  # {player_id: {'bet': amount}}
        self.hands = {}    # {player_id: [Hand]}
        self.hands_order = []  # [(player_id, hand_index)]
        self.current_hand_idx = 0  # Index actuel dans hands_order
        self.dealer_hand = Hand()  # Main du dealer
        self.deck = Deck()
        self.game_status = 'waiting'  # 'waiting', 'playing', 'finished'
        self.initial_chat_id = None

    def calculate_hand(self, hand: Hand) -> int:
        """Calcule la valeur d'une main"""
        return hand.get_value() if hand else 0

    def add_player(self, player_id: int, bet: int) -> bool:
        """Ajoute un joueur à la partie"""
        if self.game_status != 'waiting' or player_id in self.players:
            return False
        
        self.players[player_id] = {'bet': bet}
        return True

    def remove_player(self, player_id: int) -> bool:
        """Retire un joueur de la partie"""
        if self.game_status != 'waiting' or player_id not in self.players:
            return False
        
        del self.players[player_id]
        return True

    def start_game(self) -> bool:
        """Démarre la partie"""
        if self.game_status != 'waiting' or len(self.players) < 1:
            return False
            
        self.game_status = 'playing'
        self.deck.shuffle()
        
        # Distribution initiale
        for player_id in self.players:
            self.hands[player_id] = [Hand(bet=self.players[player_id]['bet'])]
            self.hands_order.append((player_id, 0))
            
            # 2 cartes par joueur
            for _ in range(2):
                self.hands[player_id][0].add_card(self.deck.deal())
        
        # 2 cartes pour le dealer
        for _ in range(2):
            self.dealer_hand.add_card(self.deck.deal())
        
        self.current_hand_idx = 0
        return True

    def get_current_player_id(self) -> Optional[int]:
        """Obtient l'ID du joueur actuel"""
        if self.game_status != 'playing':
            return None
        
        if not self.current_hand_idx < len(self.hands_order):
            return None
            
        return self.hands_order[self.current_hand_idx][0]

    def get_current_hand(self) -> Optional[Hand]:
        """Obtient la main actuelle"""
        if self.game_status != 'playing':
            return None
            
        if not self.current_hand_idx < len(self.hands_order):
            return None
            
        player_id, hand_idx = self.hands_order[self.current_hand_idx]
        return self.hands[player_id][hand_idx]

    def next_hand(self) -> bool:
        """Passe à la main suivante"""
        if self.game_status != 'playing':
            return False
            
        self.current_hand_idx += 1
        
        # Si toutes les mains ont été jouées
        if self.current_hand_idx >= len(self.hands_order):
            self.resolve_dealer()
            self.determine_winners()
            self.game_status = 'finished'
            return True
            
        return False

    def hit(self, player_id: int) -> bool:
        """Tire une carte pour le joueur actuel"""
        if not self.is_player_turn(player_id):
            return False
            
        current_hand = self.get_current_hand()
        if not current_hand or current_hand.status != 'playing':
            return False
            
        current_hand.add_card(self.deck.deal())
        
        # Vérifier si bust
        if current_hand.get_value() > 21:
            current_hand.status = 'bust'
            return self.next_hand()
            
        return True

    def stand(self, player_id: int) -> bool:
        """Le joueur reste sur sa main actuelle"""
        if not self.is_player_turn(player_id):
            return False
            
        current_hand = self.get_current_hand()
        if not current_hand or current_hand.status != 'playing':
            return False
            
        current_hand.status = 'stand'
        return self.next_hand()

    def can_split(self, player_id: int) -> bool:
        """Vérifie si le joueur peut splitter sa main"""
        if not self.is_player_turn(player_id):
            return False
            
        current_hand = self.get_current_hand()
        if not current_hand or len(current_hand.cards) != 2:
            return False
            
        return current_hand.cards[0].value == current_hand.cards[1].value

    def split_hand(self, player_id: int) -> bool:
        """Splitte la main actuelle en deux"""
        if not self.can_split(player_id):
            return False
            
        current_hand = self.get_current_hand()
        bet = current_hand.bet
        
        # Créer nouvelle main
        new_hand = Hand(bet=bet)
        new_hand.add_card(current_hand.cards.pop())
        
        # Ajouter cartes
        current_hand.add_card(self.deck.deal())
        new_hand.add_card(self.deck.deal())
        
        # Mettre à jour les mains
        player_hands = self.hands[player_id]
        hand_index = player_hands.index(current_hand)
        player_hands.insert(hand_index + 1, new_hand)
        
        # Mettre à jour l'ordre
        self.hands_order.insert(self.current_hand_idx + 1, (player_id, hand_index + 1))
        
        return True

    def is_player_turn(self, player_id: int) -> bool:
        """Vérifie si c'est le tour du joueur"""
        return (self.game_status == 'playing' and 
                self.get_current_player_id() == player_id)

    def resolve_dealer(self):
        """Résout le jeu du dealer"""
        while self.dealer_hand.get_value() < 17:
            self.dealer_hand.add_card(self.deck.deal())

    def determine_winners(self):
        """Détermine les gagnants de la partie"""
        dealer_value = self.dealer_hand.get_value()
        dealer_bust = dealer_value > 21

        for player_id, hands in self.hands.items():
            for hand in hands:
                if hand.status == 'bust':
                    continue
                    
                hand_value = hand.get_value()
                
                if hand_value == 21 and len(hand.cards) == 2:
                    hand.status = 'blackjack'
                elif dealer_bust:
                    hand.status = 'win'
                elif hand_value > dealer_value:
                    hand.status = 'win'
                elif hand_value < dealer_value:
                    hand.status = 'lose'
                else:
                    hand.status = 'push'

def start_game(self) -> bool:
        """Démarre la partie"""
        if self.game_status != 'waiting' or len(self.players) < 1:
            return False
            
        self.game_status = 'playing'
        self.deck.shuffle()
        
        # Distribuer les cartes initiales
        for player_id in self.players:
            self.hands[player_id] = [Hand(bet=self.players[player_id]['bet'])]
            self.hands_order.append((player_id, 0))
            
            # Donner 2 cartes à chaque joueur
            for _ in range(2):
                self.hands[player_id][0].add_card(self.deck.deal())
        
        # Donner 2 cartes au croupier
        for _ in range(2):
            self.dealer_hand.add_card(self.deck.deal())
        
        self.current_hand_idx = 0
        return True

def split_hand(self, player_id: int) -> bool:
    """Sépare la main actuelle en deux"""
    if not self.can_split(player_id):
        return False
            
    current_hand = self.get_current_hand()
    if not current_hand:
        return False
            
    # Créer la nouvelle main
    new_hand = Hand(bet=current_hand.bet)
    new_hand.add_card(current_hand.cards.pop())
        
    # Ajouter une carte à chaque main
    current_hand.add_card(self.deck.deal())
    new_hand.add_card(self.deck.deal())
        
    # Ajouter la nouvelle main
    player_hands = self.hands[player_id]
    hand_index = player_hands.index(current_hand)
    player_hands.insert(hand_index + 1, new_hand)
        
    # Mettre à jour hands_order
    insert_idx = self.current_hand_idx + 1
    self.hands_order.insert(insert_idx, (player_id, hand_index + 1))
        
    return True
        
# Handlers des commandes

async def display_game(update: Update, context: ContextTypes.DEFAULT_TYPE, game: MultiPlayerGame):
    chat_id = game.initial_chat_id
    
    # En-tête luxueux
    game_text = (
        "┏━━━━ 𝐂𝐀𝐒𝐈𝐍𝐎 𝐕𝐈𝐏 ━━━━┓\n"
        "┃     🎰 BLACKJACK     ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━┛\n\n"
    )

    # Affichage du croupier
    dealer_total = game.calculate_hand(game.dealer_hand)
    if game.game_status == 'finished':
        game_text += (
            "┌─── 𝐂𝐑𝐎𝐔𝐏𝐈𝐄𝐑 ───┐\n"
            f"│ {game.dealer_hand}\n"
            f"│ Total : {dealer_total}\n"
            "└──────────────────┘\n\n"
        )
    else:
        game_text += (
            "┌─── 𝐂𝐑𝐎𝐔𝐏𝐈𝐄𝐑 ───┐\n"
            f"│ {game.dealer_hand.cards[0]} ⭐\n"
            "└──────────────────┘\n\n"
        )

    # Section des joueurs
    current_player_id = game.get_current_player_id()
    total_pot = 0
    
    for player_id, player_data in game.players.items():
        player = await context.bot.get_chat(player_id)
        total_pot += player_data['bet']
        is_current = (player_id == current_player_id)
        
        # Style spécial pour le joueur actuel
        if is_current:
            game_text += (
                "🎮 𝐓𝐎𝐔𝐑 𝐀𝐂𝐓𝐔𝐄𝐋\n"
                f"┌─── {player.first_name} ───┐\n"
            )
        else:
            game_text += f"┌─── {player.first_name} ───┐\n"

        # Affichage des mains
        hands = game.hands.get(player_id, [])
        for i, hand in enumerate(hands):
            total = game.calculate_hand(hand)
            
            if len(hands) > 1:
                game_text += f"│ Main {i+1}\n"
            
            game_text += f"│ {hand}\n│ Total : {total}\n"
            
            if hand.status != 'playing':
                result_info = {
                    'blackjack': ("BLACKJACK", f"+{int(hand.bet * 2.5):,}€"),
                    'win': ("GAGNÉ", f"+{hand.bet * 2:,}€"),
                    'bust': ("BUST", f"-{hand.bet:,}€"),
                    'lose': ("PERDU", f"-{hand.bet:,}€"),
                    'push': ("ÉGALITÉ", "±0€")
                }.get(hand.status)
                
                if result_info:
                    game_text += f"│ {result_info[0]} • {result_info[1]}\n"
            
        game_text += f"│ Mise : {player_data['bet']:,}€\n"
        game_text += "└──────────────────┘\n\n"

    # Interface du joueur actuel
    keyboard = None
    if game.game_status == 'playing' and current_player_id:
        current_hand = game.get_current_hand()
        if current_hand and current_hand.status == 'playing':
            total = game.calculate_hand(current_hand)
            bust_chance = calculate_bust_probability(total)
            
            buttons = []
            row1 = [
                InlineKeyboardButton(f"🎯 CARTE ({bust_chance}%)", callback_data="hit"),
                InlineKeyboardButton("⭐ RESTER", callback_data="stand")
            ]
            buttons.append(row1)
            
            if game.can_split(current_player_id):
                row2 = [InlineKeyboardButton("✂️ SÉPARER", callback_data="split")]
                buttons.append(row2)
            
            keyboard = InlineKeyboardMarkup(buttons)

    # Pied de page
    game_text += (
        "┌─── 𝐈𝐍𝐅𝐎𝐒 ───┐\n"
        f"│ Pot : {total_pot:,}€\n"
        f"│ Joueurs : {len(game.players)}/40\n"
        "└──────────────┘"
    )

    try:
        # Gestion des messages
        if chat_id in game_messages:
            try:
                await context.bot.delete_message(chat_id, game_messages[chat_id])
            except:
                pass

        new_message = await context.bot.send_message(
            chat_id=chat_id,
            text=game_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        game_messages[chat_id] = new_message.message_id

    except Exception as e:
        game_logger.error(f"Error in display_game: {e}")

def calculate_bust_probability(total):
    """Calcule la probabilité de bust"""
    if total >= 21:
        return 100
    safe_cards = 21 - total
    return min(100, max(0, round((13 - safe_cards) / 13 * 100)))

async def format_active_player(context, player, game):
    """Format l'affichage du joueur actif"""
    emoji, rank_title, _, _ = db.get_player_rank(db.get_balance(player['id']))
    text = (
        f"▶️ *{player['name']}* ({emoji})\n"
        f"├ Mise: {player['data']['bet']:,} 💰\n"
    )
    
    for i, hand in enumerate(player['hands']):
        total = game.calculate_hand(hand)
        text += (
            f"└ {'MAIN ' + str(i+1) if len(player['hands']) > 1 else 'CARTES'}\n"
            f"  ├ {hand}\n"
            f"  └ Total: *{total}*\n"
        )
    
    return text + "\n"

async def format_waiting_player(context, player, game):
    """Format l'affichage des joueurs en attente"""
    text = f"│ {player['name']} ▫️ {player['data']['bet']:,} 💰\n"
    for hand in player['hands']:
        total = game.calculate_hand(hand)
        text += f"│ └ {hand} (*{total}*)\n"
    return text

async def format_finished_player(context, player, game):
    """Format l'affichage des joueurs ayant terminé"""
    result_emoji = "🎯" if any(h.status == 'blackjack' for h in player['hands']) else (
        "✨" if any(h.status == 'win' for h in player['hands']) else "📉"
    )
    text = f"│ {result_emoji} {player['name']}: "
    
    results = []
    for hand in player['hands']:
        total = game.calculate_hand(hand)
        if hand.status == 'blackjack':
            results.append(f"BJ ({total})")
        else:
            results.append(str(total))
    
    text += " | ".join(results) + "\n"
    return text

def calculate_game_stats(game):
    """Calcule les statistiques globales de la partie"""
    stats = {
        'blackjacks': 0,
        'busts': 0,
        'biggest_win': 0
    }
    
    for player_id, hands in game.hands.items():
        for hand in hands:
            if hand.status == 'blackjack':
                stats['blackjacks'] += 1
            elif hand.status == 'bust':
                stats['busts'] += 1
            
            if hand.status in ['blackjack', 'win']:
                win_amount = int(hand.bet * 2.5) if hand.status == 'blackjack' else hand.bet * 2
                stats['biggest_win'] = max(stats['biggest_win'], win_amount)
    
    return stats

async def format_player_results(context, player_id, game):
    """Format les résultats finaux d'un joueur"""
    try:
        player = await context.bot.get_chat(player_id)
        hands = game.hands[player_id]
        total_won = 0
        results = []
        
        for hand in hands:
            result = ""
            if hand.status == 'blackjack':
                won = int(hand.bet * 2.5)
                total_won += won
                result = f"🎯 BJ +{won:,}"
            elif hand.status == 'win':
                won = hand.bet * 2
                total_won += won
                result = f"✨ +{won:,}"
            elif hand.status in ['lose', 'bust']:
                total_won -= hand.bet
                result = f"📉 -{hand.bet:,}"
            elif hand.status == 'push':
                result = "🤝 ±0"
            
            total = game.calculate_hand(hand)
            results.append(f"{result} ({total})")
        
        result_text = (
            f"{'🔥' if total_won > 0 else '😢'} *{player.first_name}*\n"
            f"└ {' | '.join(results)}\n"
            f"  *{'+'if total_won > 0 else ''}{total_won:,}* 💰\n\n"
        )
        
        return result_text
        
    except Exception as e:
        game_logger.error(f"Error formatting results for player {player_id}: {e}")
        return ""

async def get_player_name(context: ContextTypes.DEFAULT_TYPE, player_id: int) -> str:
    """Récupère le nom d'un joueur"""
    try:
        player = await context.bot.get_chat(player_id)
        return player.first_name
    except:
        return "Joueur"

async def cmd_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le solde et les informations bancaires du joueur"""
    user = update.effective_user
    
    if not db.user_exists(user.id):
        await update.message.reply_text(
            "❌ Utilisez d'abord /start pour vous inscrire!"
        )
        return
    
    stats = db.get_stats(user.id)
    emoji, title, progress, next_rank = db.get_player_rank(stats['balance'])
    
    bank_message = (
        f"🏦 *Compte de {user.first_name}*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💰 Solde: *{stats['balance']:,}* coins\n"
        f"🎖️ Rang: {emoji} *{title}*\n"
    )
    
    if next_rank:
        progress_bar_length = 10
        filled_length = int(progress_bar_length * progress / 100)
        progress_bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)
        
        bank_message += (
            f"\n📈 *Progression*\n"
            f"├ Prochain rang: {next_rank}\n"
            f"└ [{progress_bar}] {progress:.1f}%"
        )
    else:
        bank_message += "\n👑 *Rang Maximum Atteint!*"
    
    await update.message.reply_text(
        bank_message,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le classement des joueurs"""
    rankings = db.get_leaderboard()
    
    if not rankings:
        await update.message.reply_text(
            "❌ Aucun joueur classé pour le moment."
        )
        return
    
    message = "🏆 *CLASSEMENT GLOBAL* 🏆\n━━━━━━━━━━━━━━━\n\n"
    
    for i, (username, balance) in enumerate(rankings, 1):
        emoji, title, _, _ = db.get_player_rank(balance)
        
        if i == 1:
            medal = "👑"
        elif i == 2:
            medal = "🥈"
        elif i == 3:
            medal = "🥉"
        else:
            medal = "•"
            
        message += (
            f"{medal} *{username}*\n"
            f"├ {emoji} {title}\n"
            f"└ {balance:,} 💵\n\n"
        )
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche l'aide et les règles du jeu"""
    help_text = (
        "🎰 *BLACKJACK - RÈGLES DU JEU* 🎰\n\n"
        "*🎯 Objectif:*\n"
        "└ Obtenir un total plus proche de 21 que le croupier\n"
        "└ Ne pas dépasser 21\n\n"
        "*🃏 Valeurs des cartes:*\n"
        "└ As ➜ 1 ou 11\n"
        "└ Roi, Dame, Valet ➜ 10\n"
        "└ Autres cartes ➜ Valeur faciale\n\n"
        "*💰 Gains:*\n"
        "└ Blackjack (21) ➜ x2.5\n"
        "└ Victoire ➜ x2\n"
        "└ Égalité ➜ Mise remboursée\n\n"
        "*✂️ Split:*\n"
        "└ Possible avec deux cartes identiques\n"
        "└ Nécessite une mise égale à la mise initiale\n"
        "└ Chaque main est jouée séparément\n\n"
        "*📌 Limites:*\n"
        "└ Mise min: 10 coins\n"
        "└ Mise max: 1.000.000 coins\n"
        f"└ {MAX_PLAYERS} joueurs maximum\n\n"
        "*📋 Commandes:*\n"
        "└ /bj [mise] - Jouer\n"
        "└ /daily - Bonus quotidien\n"
        "└ /stats - Statistiques\n"
        "└ /bank - Voir solde\n"
        "└ /top - Classement"
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def check_timeouts(context: ContextTypes.DEFAULT_TYPE):
    """Vérifie les timeouts des parties en cours"""
    games_to_check = list(active_games.items())
    for game_id, game in games_to_check:
        if game.game_status == 'playing' and game.check_timeout():
            try:
                current_player_id = game.get_current_player_id()
                if current_player_id:
                    current_hand = game.get_current_hand()
                    if current_hand and current_hand.status == 'playing':
                        current_hand.status = 'stand'
                        game_ended = game.next_hand()
                        
                        if game_ended:
                            game.game_status = 'finished'
                            game.resolve_dealer()
                            game.determine_winners()
                        
                        # Créer un faux update pour display_game
                        dummy_update = Update(0, None)
                        await display_game(dummy_update, context, game)
                        
            except Exception as e:
                game_logger.error(f"Error in check_timeouts: {e}")

async def update_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    """Met à jour le message du classement"""
    if CLASSEMENT_MESSAGE_ID and CLASSEMENT_CHAT_ID:
        try:
            rankings = db.get_leaderboard()
            if rankings:
                message = "🏆 *CLASSEMENT LIVE* 🏆\n━━━━━━━━━━━━━━━\n\n"
                
                for i, (username, balance) in enumerate(rankings, 1):
                    emoji, title, _, _ = db.get_player_rank(balance)
                    medal = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "•"
                    
                    message += (
                        f"{medal} *{username}*\n"
                        f"├ {emoji} {title}\n"
                        f"└ {balance:,} 💵\n\n"
                    )
                
                await context.bot.edit_message_text(
                    chat_id=CLASSEMENT_CHAT_ID,
                    message_id=CLASSEMENT_MESSAGE_ID,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            game_logger.error(f"Error updating leaderboard: {e}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if not db.user_exists(user.id):
        if db.register_user(user.id, user.first_name):
            welcome_message = (
                f"👋 Bienvenue {user.first_name} !\n\n"
                f"🎮 Blackjack Multi-joueurs\n"
                f"💰 Bonus de départ : {INITIAL_BALANCE} coins\n\n"
                f"*Commandes principales :*\n"
                f"└ /bj [mise] - Jouer au Blackjack\n"
                f"└ /daily - Bonus quotidien\n"
                f"└ /stats - Vos statistiques\n"
                f"└ /bank - Voir votre solde\n"
                f"└ /help - Aide et règles"
            )
        else:
            welcome_message = "❌ Erreur lors de l'inscription. Réessayez."
    else:
        stats = db.get_stats(user.id)
        emoji, title, progress, next_rank = db.get_player_rank(stats['balance'])
        
        welcome_message = (
            f"👋 Re-bonjour {user.first_name} !\n\n"
            f"💰 Solde : {stats['balance']:,} coins\n"
            f"{emoji} Rang : {title}\n"
        )
        
        if next_rank:
            welcome_message += f"📈 Progression : {progress:.1f}% vers {next_rank}\n"
        
        welcome_message += (
            f"\n*Commandes disponibles :*\n"
            f"└ /bj [mise] - Jouer\n"
            f"└ /daily - Bonus quotidien\n"
            f"└ /stats - Statistiques\n"
            f"└ /bank - Solde\n"
            f"└ /top - Classement"
        )
    
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)

async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    can_claim, time_remaining = db.can_claim_daily(user.id)
    
    if not can_claim:
        hours, remainder = divmod(time_remaining.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        await update.message.reply_text(
            f"⏳ *Bonus non disponible*\n\n"
            f"Revenez dans:\n"
            f"└ {hours}h {minutes}m {seconds}s",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if db.claim_daily(user.id):
        balance = db.get_balance(user.id)
        await update.message.reply_text(
            f"🎁 *BONUS QUOTIDIEN !*\n\n"
            f"💰 +{DAILY_AMOUNT:,} coins\n"
            f"💳 Nouveau solde: {balance:,} coins",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ Une erreur s'est produite.")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = db.get_stats(user.id)
    emoji, rank_title, progress, next_rank = db.get_player_rank(stats['balance'])
    
    progress_bar_length = 10
    filled_length = int(progress_bar_length * progress / 100)
    progress_bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)
    
    win_rate = (stats['games_won'] / stats['games_played'] * 100) if stats['games_played'] > 0 else 0
    
    stats_text = (
        f"*STATISTIQUES DE {user.first_name}*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💵 *Solde:* {stats['balance']:,} coins\n"
        f"🎖️ *Rang:* {emoji} {rank_title}\n"
    )
    
    if next_rank:
        stats_text += (
            f"\n*Progression vers {next_rank}*\n"
            f"[{progress_bar}] {progress:.1f}%\n"
        )
    else:
        stats_text += "\n🏆 *Rang Maximum Atteint !*\n"
    
    stats_text += (
        f"\n📊 *Statistiques de Jeu*\n"
        f"├ Parties jouées: {stats['games_played']}\n"
        f"├ Victoires: {stats['games_won']}\n"
        f"├ Splits réussis: {stats['games_split']}\n"
        f"├ Taux de victoire: {win_rate:.1f}%\n"
        f"├ Total parié: {stats['total_bets']:,} coins\n"
        f"└ Plus gros gain: {stats['biggest_win']:,} coins\n"
    )
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
def cleanup_player_games(player_id: int):
    """Nettoie les anciennes parties d'un joueur"""
    # Supprimer les parties en attente du joueur
    if player_id in waiting_games:
        waiting_games.remove(player_id)
    
    # Supprimer toutes les parties actives où le joueur est présent
    games_to_remove = []
    for game_id, game in active_games.items():
        if player_id in game.players:
            # Si c'est une partie terminée ou en attente
            if game.game_status in ['finished', 'waiting']:
                games_to_remove.append(game_id)
            # Si c'est une partie en cours, marquer le joueur comme "stand"
            elif game.game_status == 'playing':
                current_player = game.get_current_player_id()
                if current_player == player_id:
                    if current_hand := game.get_current_hand():
                        current_hand.status = 'stand'
                        game.next_hand()
    
    # Supprimer les parties identifiées
    for game_id in games_to_remove:
        if game_id in active_games:
            del active_games[game_id]

    game_logger.debug(f"Cleaned up games for player {player_id}")

async def create_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message or update.edited_message
    chat_id = message.chat_id
    
    # Vérifier s'il y a déjà une partie en cours
    for g in active_games.values():
        if hasattr(g, 'initial_chat_id') and g.initial_chat_id == chat_id and g.game_status == 'playing':
            error_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Une partie est déjà en cours dans ce chat!"
            )
            await message.delete()
            await asyncio.sleep(3)
            await error_msg.delete()
            return
    
    try:
        bet_amount = int(context.args[0])
    except (IndexError, ValueError):
        error_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Mise invalide.\n`/bj [mise]`\nExemple: `/bj 100`",
            parse_mode=ParseMode.MARKDOWN
        )
        await message.delete()
        await asyncio.sleep(3)
        await error_msg.delete()
        return
    
    if bet_amount < 10 or bet_amount > 1000000:
        error_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Mise entre 10 et 1.000.000 coins."
        )
        await message.delete()
        await asyncio.sleep(3)
        await error_msg.delete()
        return
    
    # Vérifier le solde
    balance = db.get_balance(user.id)
    if balance < bet_amount:
        error_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Solde insuffisant!\nVotre solde: {balance:,} coins"
        )
        await message.delete()
        await asyncio.sleep(3)
        await error_msg.delete()
        return

    # Vérifier partie en attente
    existing_game = None
    for g in active_games.values():
        if g.game_status == 'waiting':
            existing_game = g
            break

    if existing_game:
        if user.id in existing_game.players:
            error_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Vous êtes déjà dans cette partie!"
            )
            await message.delete()
            await asyncio.sleep(3)
            await error_msg.delete()
            return

        if existing_game.add_player(user.id, bet_amount):
            await display_waiting_game(update, context, existing_game)
        else:
            error_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Impossible de rejoindre la partie!"
            )
            await message.delete()
            await asyncio.sleep(3)
            await error_msg.delete()
        return

    # Créer nouvelle partie
    cleanup_player_games(user.id)
    game = MultiPlayerGame(user.id, user.first_name)
    game.initial_chat_id = chat_id
    game.add_player(user.id, bet_amount)
    active_games[user.id] = game
    waiting_games.add(user.id)
    
    await display_waiting_game(update, context, game)

async def display_waiting_game(update: Update, context: ContextTypes.DEFAULT_TYPE, game: MultiPlayerGame):
    chat_id = game.initial_chat_id
    
    players_text = "*👥 JOUEURS:*\n"
    total_bets = 0

    for player_id in game.players:
        player = await context.bot.get_chat(player_id)
        bet = game.players[player_id]['bet']
        emoji, rank_title, _, _ = db.get_player_rank(db.get_balance(player_id))
        total_bets += bet
        
        players_text += (
            f"└ {emoji} {player.first_name} ➜ {bet:,} 💵\n"
            f"   ├ Rang: {rank_title}\n"
            f"   └ Gains possibles:\n"
            f"      ├ Blackjack: +{int(bet * 2.5):,} 💵\n"
            f"      └ Victoire: +{bet * 2:,} 💵\n"
        )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎮 LANCER LA PARTIE", callback_data="start_game")
    ]])

    # Supprimer ancien message
    if chat_id in last_game_message:
        try:
            await context.bot.delete_message(chat_id, last_game_message[chat_id])
        except:
            pass

    new_message = await context.bot.send_message(
        chat_id=chat_id,
        text=f"*🎰 PARTIE EN ATTENTE*\n"
             f"━━━━━━━━━━\n\n"
             f"{players_text}\n"
             f"*ℹ️ INFOS:*\n"
             f"├ {len(game.players)}/{MAX_PLAYERS} places\n"
             f"├ 💰 Total mises: {total_bets:,} 💵\n"
             f"└ ⏳ Expire dans 5 minutes\n\n"
             f"📢 Pour rejoindre:\n"
             f"`/bj [mise]`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    
    last_game_message[chat_id] = new_message.message_id

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    if query.data == "start_game":
        game = None
        for g in active_games.values():
            if g.host_id == user.id and g.game_status == 'waiting':
                game = g
                break
        
        if not game:
            await query.answer("❌ Vous n'êtes pas le créateur!")
            return
            
        if game.start_game():
            await display_game(update, context, game)
            await query.answer("✅ La partie commence!")
        else:
            await query.answer("❌ Impossible de démarrer!")
        return

    # Trouver la partie active
    game = None
    for g in active_games.values():
        if hasattr(g, 'initial_chat_id') and g.initial_chat_id == chat_id:
            game = g
            break
    
    if not game:
        await query.answer("❌ Aucune partie en cours!")
        return

    current_player_id = game.get_current_player_id()
    if user.id != current_player_id:
        await query.answer("⏳ Ce n'est pas votre tour!")
        return

    # Trouver la partie active du joueur
    game = None
    for g in active_games.values():
        if user.id in g.players:
            game = g
            break
    
    if not game or game.get_current_player_id() != user.id:
        await query.answer("❌ Ce n'est pas votre tour!")
        return

    current_hand = game.get_current_hand()
    if not current_hand:
        await query.answer("❌ Erreur: main invalide!")
        return

    try:
        if query.data == "hit":
            card = game.deck.deal()
            current_hand.add_card(card)
            total = current_hand.get_value()
            
            if total > 21:
                current_hand.status = 'bust'
                game_ended = game.next_hand()
                await query.answer("💥 Bust!")
            else:
                await query.answer(f"🎯 Total: {total}")
                
        elif query.data == "stand":
            current_hand.status = 'stand'
            game_ended = game.next_hand()
            await query.answer("⏹ Stand")
            
        elif query.data == "split":
            if not game.can_split(user.id):
                await query.answer("❌ Split impossible!")
                return
                
            current_bet = current_hand.bet
            if db.get_balance(user.id) < current_bet:
                await query.answer("❌ Solde insuffisant pour split!")
                return
                
            db.set_balance(user.id, db.get_balance(user.id) - current_bet)
            if game.split_hand(user.id):
                await query.answer("✂️ Main séparée!")
            else:
                await query.answer("❌ Erreur lors du split!")
                return

        await display_game(update, context, game)
        
    except Exception as e:
        game_logger.error(f"Error in button_handler: {e}")
        await query.answer("❌ Une erreur s'est produite!")

def main():
    defaults = Defaults(parse_mode=ParseMode.MARKDOWN)
    application = (
        Application.builder()
        .token(TOKEN)
        .defaults(defaults)
        .build()
    )
    
    # Commandes
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("bj", create_game))
    application.add_handler(CommandHandler("daily", cmd_daily))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("bank", cmd_bank))
    application.add_handler(CommandHandler("top", cmd_top))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Jobs
    application.job_queue.run_repeating(check_timeouts, interval=5)
    application.job_queue.run_repeating(update_leaderboard, interval=300)
    
    game_logger.info("🎲 Blackjack Bot démarré!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
