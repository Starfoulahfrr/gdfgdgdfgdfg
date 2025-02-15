import sqlite3
from datetime import datetime

class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect('blackjack.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.setup_database()
    
    def setup_database(self):
        """Initialise la structure de la base de données si elle n'existe pas"""
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                total_bets INTEGER DEFAULT 0,
                biggest_win INTEGER DEFAULT 0,
                last_daily DATETIME
            );
            
            CREATE TABLE IF NOT EXISTS game_history (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bet_amount INTEGER,
                result TEXT,
                timestamp DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
        ''')
        self.conn.commit()
    
    def get_balance(self, user_id: int) -> int:
        try:
            self.cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            print(f"Erreur dans get_balance: {e}")
            return 0

    def update_game_result(self, user_id: int, bet_amount: int, result: str):
        try:
            multiplier = {
                'win': 2,
                'blackjack': 2.5,
                'lose': 0,
                'push': 1,
                'dice_win': 1.2,
            }.get(result, 0)
            
            winnings = int(bet_amount * multiplier)
            
            self.cursor.execute('''
                UPDATE users 
                SET balance = balance + ?,
                    games_played = games_played + 1,
                    games_won = games_won + CASE WHEN ? IN ('win', 'blackjack', 'dice_win') THEN 1 ELSE 0 END,
                    total_bets = total_bets + ?,
                    biggest_win = CASE 
                        WHEN ? > biggest_win AND ? IN ('win', 'blackjack', 'dice_win')
                        THEN ? ELSE biggest_win 
                    END
                WHERE user_id = ?
            ''', (winnings - bet_amount, result, bet_amount, winnings, result, winnings, user_id))
            
            self.cursor.execute('''
                INSERT INTO game_history (user_id, bet_amount, result, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, bet_amount, result, datetime.utcnow()))
            
            self.conn.commit()
        except Exception as e:
            print(f"Erreur dans update_game_result: {e}")
            self.conn.rollback()

    def user_exists(self, user_id: int) -> bool:
        """Vérifie si un utilisateur existe dans la base de données"""
        self.cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None

    def close(self):
        """Ferme la connexion à la base de données"""
        self.conn.close()

# Créez l'instance de la base de données
db = DatabaseManager()

# Liste des administrateurs
ADMIN_USERS = [5277718388, 5909979625]

def is_admin(user_id: int) -> bool:
    """Vérifie si l'utilisateur est administrateur"""
    return user_id in ADMIN_USERS