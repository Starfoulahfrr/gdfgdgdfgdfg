import json
import logging
import asyncio
import shutil
import os
from data import stats
from datetime import datetime, time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters, 
    ContextTypes, 
    ConversationHandler
)

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Charger la configuration
try:
    with open('config/config.json', 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
        TOKEN = CONFIG['token']
        ADMIN_IDS = CONFIG['admin_ids']
except FileNotFoundError:
    print("Erreur: Le fichier config.json n'a pas été trouvé!")
    exit(1)
except KeyError as e:
    print(f"Erreur: La clé {e} est manquante dans le fichier config.json!")
    exit(1)

# Fonctions de gestion du catalogue
def load_catalog():
    try:
        with open(CONFIG['catalog_file'], 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_catalog(catalog):
    with open(CONFIG['catalog_file'], 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=4, ensure_ascii=False)


def save_active_users(users_data):
    """Sauvegarde les données des utilisateurs actifs dans un fichier"""
    try:
        with open('data/active_users.json', 'w', encoding='utf-8') as f:
            # Convertir les IDs en strings pour le JSON
            data = {str(user_id): info for user_id, info in users_data.items()}
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Erreur lors de la sauvegarde des utilisateurs actifs: {e}")

def load_active_users():
    """Charge les données des utilisateurs actifs depuis le fichier"""
    try:
        with open('data/active_users.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):  # Ancien format (liste d'IDs)
                # Convertir en nouveau format
                return {int(user_id): {
                    'username': None,
                    'first_name': None,
                    'last_name': None,
                    'last_seen': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                } for user_id in data}
            else:  # Nouveau format (dictionnaire)
                return {int(k): v for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Erreur lors du chargement des utilisateurs actifs: {e}")
        return {}

def backup_data():
    """Crée une sauvegarde des fichiers de données"""
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Backup config.json
    if os.path.exists("config/config.json"):
        shutil.copy2("config/config.json", f"{backup_dir}/config_{timestamp}.json")
    
    # Backup catalog.json
    if os.path.exists("config/catalog.json"):
        shutil.copy2("config/catalog.json", f"{backup_dir}/catalog_{timestamp}.json")

def print_catalog_debug():
    """Fonction de debug pour afficher le contenu du catalogue"""
    for category, products in CATALOG.items():
            print(f"\nCatégorie: {category}")
            for product in products:
                print(f"  Produit: {product['name']}")
                if 'media' in product:
                    print(f"    Médias ({len(product['media'])}): {product['media']}")

# États de conversation
CHOOSING = "CHOOSING"
WAITING_CATEGORY_NAME = "WAITING_CATEGORY_NAME"
WAITING_PRODUCT_NAME = "WAITING_PRODUCT_NAME"
WAITING_PRODUCT_PRICE = "WAITING_PRODUCT_PRICE"
WAITING_PRODUCT_DESCRIPTION = "WAITING_PRODUCT_DESCRIPTION"
WAITING_PRODUCT_MEDIA = "WAITING_PRODUCT_MEDIA"
SELECTING_CATEGORY = "SELECTING_CATEGORY"
SELECTING_CATEGORY_TO_DELETE = "SELECTING_CATEGORY_TO_DELETE"
SELECTING_PRODUCT_TO_DELETE = "SELECTING_PRODUCT_TO_DELETE"
WAITING_CONTACT_USERNAME = "WAITING_CONTACT_USERNAME"
SELECTING_PRODUCT_TO_EDIT = "SELECTING_PRODUCT_TO_EDIT"
EDITING_PRODUCT_FIELD = "EDITING_PRODUCT_FIELD"
WAITING_NEW_VALUE = "WAITING_NEW_VALUE"
WAITING_BROADCAST_MESSAGE = "WAITING_BROADCAST_MESSAGE"
WAITING_BANNER_IMAGE = "WAITING_BANNER_IMAGE"

# Charger le catalogue au démarrage
CATALOG = load_catalog()

# Fonctions de base
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if 'active_users' not in context.bot_data:
        context.bot_data['active_users'] = load_active_users()

    context.bot_data['active_users'][user.id] = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'last_seen': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_active_users(context.bot_data['active_users'])
    
    # Sauvegarder les informations de l'utilisateur
    context.bot_data['active_users'][user.id] = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'last_seen': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_active_users(context.bot_data['active_users'])
    # Supprimer le message /start
    await update.message.delete()
    
    # Supprimer les anciens messages si nécessaire
    if 'menu_message_id' in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=context.user_data['menu_message_id']
            )
        except:
            pass
    
    # Nouveau clavier simplifié pour l'accueil
    keyboard = [
        [InlineKeyboardButton("📋 MENU", callback_data="show_categories")]
    ]

    # Ajouter le bouton admin si l'utilisateur est administrateur
    if str(update.effective_user.id) in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔧 Menu Admin", callback_data="admin")])

    # Ajouter les boutons de contact et canaux
    keyboard.extend([
        [
            InlineKeyboardButton("📞 Contact telegram", url=f"https://t.me/{CONFIG['contact_username']}"),
            InlineKeyboardButton("📝 Exemple bouton 1", url="https://www.google.fr/"),
        ],
        [InlineKeyboardButton("🥔 Exemple bouton 2", url="https://www.google.fr")]
    ])
    
    welcome_text = (
        "🌿 *Bienvenue sur mon bot test !* 🌿\n\n"
        "Ce bot est juste un bot MENU en TEST, vous pouvez voir les fonctionnalités UTILISATEUR.\n\n"
        "📋 Cliquez sur MENU pour voir les catégories"
    )

    try:
        # Vérifier si une image banner est configurée
        if CONFIG.get('banner_image'):
            # Si un ancien message banner existe, le supprimer
            # if 'banner_message_id' in context.user_data:
            #     try:
            #         await context.bot.delete_message(
            #             chat_id=chat_id,
            #             message_id=context.user_data['banner_message_id']
            #         )
            #     except:
            #         pass
            
            # Envoyer la nouvelle image banner
            banner_message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=CONFIG['banner_image']
            )
            context.user_data['banner_message_id'] = banner_message.message_id

        # Envoyer le menu d'accueil
        menu_message = await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        context.user_data['menu_message_id'] = menu_message.message_id
        
    except Exception as e:
        print(f"Erreur lors du démarrage: {e}")
        # En cas d'erreur, envoyer au moins le menu
        menu_message = await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        context.user_data['menu_message_id'] = menu_message.message_id
    
    return CHOOSING

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande pour accéder au menu d'administration"""
    if str(update.effective_user.id) in ADMIN_IDS:
        return await show_admin_menu(update, context)
    else:
        await update.message.reply_text("❌ Vous n'êtes pas autorisé à accéder au menu d'administration.")
        return ConversationHandler.END

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le menu d'administration"""
    keyboard = [
        [InlineKeyboardButton("➕ Ajouter une catégorie", callback_data="add_category")],
        [InlineKeyboardButton("➕ Ajouter un produit", callback_data="add_product")],
        [InlineKeyboardButton("❌ Supprimer une catégorie", callback_data="delete_category")],
        [InlineKeyboardButton("❌ Supprimer un produit", callback_data="delete_product")],
        [InlineKeyboardButton("✏️ Modifier un produit", callback_data="edit_product")],
        [InlineKeyboardButton("📞 Modifier le contact", callback_data="edit_contact")],
        [InlineKeyboardButton("📢 Envoyer une annonce", callback_data="start_broadcast")],
        [InlineKeyboardButton("👥 Gérer utilisateurs", callback_data="manage_users")],
        [InlineKeyboardButton("🖼️ Modifier image bannière", callback_data="edit_banner_image")],
        [InlineKeyboardButton("📊 Voir les statistiques", callback_data="show_stats")],
        [InlineKeyboardButton("🔙 Retour à l'accueil", callback_data="back_to_home")]
    ]

    admin_text = (
        "🔧 *Menu d'administration*\n\n"
        "Sélectionnez une action à effectuer :"
    )

    try:
        if update.callback_query:
            message = await update.callback_query.edit_message_text(
                admin_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            context.user_data['menu_message_id'] = message.message_id
        else:
            message = await update.message.reply_text(
                admin_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            context.user_data['menu_message_id'] = message.message_id
    except Exception as e:
        print(f"Erreur dans show_admin_menu: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    return CHOOSING

async def handle_banner_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'ajout de l'image bannière"""
    if not update.message.photo:
        await update.message.reply_text("Veuillez envoyer une photo.")
        return WAITING_BANNER_IMAGE

    # Obtenir l'ID du fichier de la photo
    file_id = update.message.photo[-1].file_id
    CONFIG['banner_image'] = file_id

    # Sauvegarder la configuration
    with open('config/config.json', 'w', encoding='utf-8') as f:
        json.dump(CONFIG, f, indent=4)

    # Supprimer le message contenant l'image
    await update.message.delete()

    # Envoyer le message de confirmation
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Image bannière mise à jour avec succès !"
    )

    return await show_admin_menu(update, context)

async def daily_maintenance(context: ContextTypes.DEFAULT_TYPE):
    """Tâches de maintenance quotidiennes"""
    try:
        # Backup des données
        backup_data()
        
        # Nettoyage des utilisateurs inactifs
        await clean_inactive_users(context)
        
        
    except Exception as e:
        print(f"Erreur lors de la maintenance quotidienne : {e}")

async def handle_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'ajout d'une nouvelle catégorie"""
    category_name = update.message.text
    
    if category_name in CATALOG:
        await update.message.reply_text(
            "❌ Cette catégorie existe déjà. Veuillez choisir un autre nom:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_category")
            ]])
        )
        return WAITING_CATEGORY_NAME
    
    CATALOG[category_name] = []
    save_catalog(CATALOG)
    
    # Supprimer le message précédent
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id - 1
    )
    
    # Supprimer le message de l'utilisateur
    await update.message.delete()
    
    return await show_admin_menu(update, context)

async def handle_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'entrée du nom du produit"""
    product_name = update.message.text
    category = context.user_data.get('temp_product_category')
    
    if category and any(p.get('name') == product_name for p in CATALOG.get(category, [])):
        await update.message.reply_text(
            "❌ Ce produit existe déjà dans cette catégorie. Veuillez choisir un autre nom:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")
            ]])
        )
        return WAITING_PRODUCT_NAME
    
    context.user_data['temp_product_name'] = product_name
    
    # Supprimer le message précédent
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id - 1
    )
    
    await update.message.reply_text(
        "💰 Veuillez entrer le prix du produit:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")
        ]])
    )
    
    # Supprimer le message de l'utilisateur
    await update.message.delete()
    
    return WAITING_PRODUCT_PRICE

async def handle_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'entrée du prix du produit"""
    price = update.message.text
    context.user_data['temp_product_price'] = price
    
    # Supprimer le message précédent
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id - 1
    )
    
    await update.message.reply_text(
        "📝 Veuillez entrer la description du produit:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")
        ]])
    )
    
    # Supprimer le message de l'utilisateur
    await update.message.delete()
    
    return WAITING_PRODUCT_DESCRIPTION

async def handle_product_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'entrée de la description du produit"""
    description = update.message.text
    context.user_data['temp_product_description'] = description
    
    # Initialiser la liste des médias
    context.user_data['temp_product_media'] = []
    
    # Supprimer le message précédent
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id - 1
    )
    
    # Envoyer et sauvegarder l'ID du message d'invitation
    invitation_message = await update.message.reply_text(
        "📸 Envoyez les photos ou vidéos du produit (plusieurs possibles)\n"
        "Si vous ne voulez pas en envoyer, cliquez sur ignorer* :",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏩ Ignorer", callback_data="skip_media")],
            [InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")]
        ])
    )
    context.user_data['media_invitation_message_id'] = invitation_message.message_id
    
    # Supprimer le message de l'utilisateur
    await update.message.delete()
    
    return WAITING_PRODUCT_MEDIA

async def handle_product_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'ajout des médias (photos ou vidéos) du produit"""
    if not (update.message.photo or update.message.video):
        await update.message.reply_text("Veuillez envoyer une photo ou une vidéo.")
        return WAITING_PRODUCT_MEDIA

    if 'temp_product_media' not in context.user_data:
        context.user_data['temp_product_media'] = []

    if 'media_count' not in context.user_data:
        context.user_data['media_count'] = 0

    if context.user_data.get('media_invitation_message_id'):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['media_invitation_message_id']
            )
            del context.user_data['media_invitation_message_id']
        except Exception as e:
            print(f"Erreur lors de la suppression du message d'invitation: {e}")

    if context.user_data.get('last_confirmation_message_id'):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['last_confirmation_message_id']
            )
        except Exception as e:
            print(f"Erreur lors de la suppression du message de confirmation: {e}")

    context.user_data['media_count'] += 1

    if update.message.photo:
        media_id = update.message.photo[-1].file_id
        media_type = 'photo'
    else:
        media_id = update.message.video.file_id
        media_type = 'video'

    new_media = {
        'media_id': media_id,
        'media_type': media_type,
        'order_index': context.user_data['media_count']
    }

    context.user_data['temp_product_media'].append(new_media)

    await update.message.delete()

    message = await update.message.reply_text(
        f"Photo/Vidéo {context.user_data['media_count']} ajoutée ! Cliquez sur Terminé pour valider :",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Terminé", callback_data="finish_media")],
            [InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")]
        ])
    )
    context.user_data['last_confirmation_message_id'] = message.message_id

    return WAITING_PRODUCT_MEDIA

async def finish_product_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = context.user_data.get('temp_product_category')
    if not category:
        return await show_admin_menu(update, context)

    new_product = {
        'name': context.user_data.get('temp_product_name'),
        'price': context.user_data.get('temp_product_price'),
        'description': context.user_data.get('temp_product_description'),
        'media': context.user_data.get('temp_product_media', [])
    }

    if category not in CATALOG:
        CATALOG[category] = []
    CATALOG[category].append(new_product)
    save_catalog(CATALOG)

    try:
        await query.message.delete()
    except Exception as e:
        print(f"Erreur lors de la suppression du message: {e}")

    context.user_data.clear()

    # Rediriger vers le menu administrateur après l'ajout du produit
    return await show_admin_menu(update, context)

async def handle_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la nouvelle valeur pour le champ en cours de modification"""
    category = context.user_data.get('editing_category')
    product_name = context.user_data.get('editing_product')
    field = context.user_data.get('editing_field')
    new_value = update.message.text

    if not all([category, product_name, field]):
        await update.message.reply_text("❌ Une erreur est survenue. Veuillez réessayer.")
        return await show_admin_menu(update, context)

    for product in CATALOG.get(category, []):
        if product['name'] == product_name:
            old_value = product.get(field)
            product[field] = new_value
            save_catalog(CATALOG)

            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id - 1
            )
            await update.message.delete()

            keyboard = [[InlineKeyboardButton("🔙 Retour au menu", callback_data="admin")]]
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ Modification effectuée avec succès !\n\n"
                     f"Ancien {field}: {old_value}\n"
                     f"Nouveau {field}: {new_value}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            break

    return CHOOSING

async def handle_contact_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la modification du nom d'utilisateur de contact"""
    new_username = update.message.text.replace("@", "")
    CONFIG['contact_username'] = new_username
    
    # Sauvegarder la configuration
    with open('config/config.json', 'w', encoding='utf-8') as f:
        json.dump(CONFIG, f, indent=4)
    
    # Supprimer le message précédent
    await context.bot.delete_message(
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id - 1
    )
    
    # Supprimer le message de l'utilisateur
    await update.message.delete()
    
    return await show_admin_menu(update, context)

async def handle_normal_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestion des boutons normaux"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin":
        if str(update.effective_user.id) in ADMIN_IDS:
            return await show_admin_menu(update, context)
        else:
            await query.edit_message_text("❌ Vous n'êtes pas autorisé à accéder au menu d'administration.")
            return CHOOSING

    elif query.data == "edit_banner_image":
        await query.message.edit_text(
            "📸 Veuillez envoyer la nouvelle image bannière :",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit")
            ]])
        )
        return WAITING_BANNER_IMAGE

    elif query.data == "show_stats":
        stats_data = stats.load_stats()
        text = "📊 *Statistiques du catalogue*\n\n"
        text += f"👥 Vues totales: {stats_data.get('total_views', 0)}\n\n"
        
        text += "🔥 *Produits les plus populaires:*\n"
        product_views = stats_data.get('product_views', {})
        if product_views:
            all_products = []
            for category, products in product_views.items():
                if category in CATALOG:  # Vérifier que la catégorie existe
                    existing_products = [p['name'] for p in CATALOG[category]]
                    for product_name, views in products.items():
                        if product_name in existing_products:  # Vérifier que le produit existe
                            all_products.append((category, product_name, views))
            
            # Trier par nombre de vues et prendre les 5 premiers
            sorted_products = sorted(all_products, key=lambda x: x[2], reverse=True)[:5]
            for category, product_name, views in sorted_products:
                text += f"- {product_name} ({category}): {views} vues\n"
        else:
            text += "Aucune vue enregistrée sur les produits.\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Réinitialiser les statistiques", callback_data="reset_stats")],
            [InlineKeyboardButton("🔙 Retour", callback_data="admin")]
        ]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return CHOOSING

    elif query.data == "reset_stats":
        stats_data = {
            'total_views': 0,
            'category_views': {},
            'product_views': {},
            'last_updated': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            'last_reset': datetime.utcnow().strftime("%Y-%m-%d")
        }
        stats.save_stats(stats_data)
        await query.edit_message_text(
            "✅ Les statistiques ont été réinitialisées.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="admin")]]),
            parse_mode='Markdown'
        )
        return CHOOSING

    elif query.data == "add_category":
        await query.message.edit_text(
            "📝 Veuillez entrer le nom de la nouvelle catégorie:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_category")
            ]])
        )
        return WAITING_CATEGORY_NAME

    elif query.data == "add_product":
        keyboard = []
        for category in CATALOG.keys():
                keyboard.append([InlineKeyboardButton(category, callback_data=f"select_category_{category}")])
        keyboard.append([InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")])
        
        await query.message.edit_text(
            "📝 Sélectionnez la catégorie pour le nouveau produit:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECTING_CATEGORY

    elif query.data.startswith("select_category_"):
        # Ne traiter que si ce n'est PAS une action de suppression
        if not query.data.startswith("select_category_to_delete_"):
            category = query.data.replace("select_category_", "")
            context.user_data['temp_product_category'] = category
            
            await query.message.edit_text(
                "📝 Veuillez entrer le nom du nouveau produit:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Annuler", callback_data="cancel_add_product")
                ]])
            )
            return WAITING_PRODUCT_NAME

    elif query.data.startswith("delete_product_category_"):
        category = query.data.replace("delete_product_category_", "")
        products = CATALOG.get(category, [])
    
        keyboard = []
        for product in products:
            if isinstance(product, dict):
                keyboard.append([
                    InlineKeyboardButton(
                        product['name'], 
                        callback_data=f"confirm_delete_product_{category}_{product['name']}"
                    )
                ])
        keyboard.append([InlineKeyboardButton("🔙 Annuler", callback_data="cancel_delete_product")])
    
        await query.message.edit_text(
            f"⚠️ Sélectionnez le produit à supprimer de *{category}* :",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return SELECTING_PRODUCT_TO_DELETE

    elif query.data == "delete_category":
        keyboard = []
        for category in CATALOG.keys():
                keyboard.append([InlineKeyboardButton(category, callback_data=f"confirm_delete_category_{category}")])
        keyboard.append([InlineKeyboardButton("🔙 Annuler", callback_data="cancel_delete_category")])
        
        await query.message.edit_text(
            "⚠️ Sélectionnez la catégorie à supprimer:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECTING_CATEGORY_TO_DELETE

    elif query.data.startswith("confirm_delete_category_"):
        # Ajoutez une étape de confirmation
        category = query.data.replace("confirm_delete_category_", "")
        keyboard = [
            [
                InlineKeyboardButton("✅ Oui, supprimer", callback_data=f"really_delete_category_{category}"),
                InlineKeyboardButton("❌ Non, annuler", callback_data="cancel_delete_category")
            ]
        ]
        await query.message.edit_text(
            f"⚠️ *Êtes-vous sûr de vouloir supprimer la catégorie* `{category}` *?*\n\n"
            f"Cette action supprimera également tous les produits de cette catégorie.\n"
            f"Cette action est irréversible !",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return SELECTING_CATEGORY_TO_DELETE


    elif query.data.startswith("really_delete_category_"):
        category = query.data.replace("really_delete_category_", "")
        if category in CATALOG:
            del CATALOG[category]
            save_catalog(CATALOG)
            await query.message.edit_text(
                f"✅ La catégorie *{category}* a été supprimée avec succès !",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Retour au menu", callback_data="admin")
                ]])
            )
        return CHOOSING

    elif query.data == "delete_product":
        keyboard = []
        for category in CATALOG.keys():
                keyboard.append([
                    InlineKeyboardButton(
                        category, 
                        callback_data=f"delete_product_category_{category}"
                    )
                ])
        keyboard.append([InlineKeyboardButton("🔙 Annuler", callback_data="cancel_delete_product")])
        
        await query.message.edit_text(
            "⚠️ Sélectionnez la catégorie du produit à supprimer:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECTING_CATEGORY_TO_DELETE

    elif query.data.startswith("confirm_delete_product_"):
        try:
            # Extraire la catégorie et le nom du produit
            parts = query.data.replace("confirm_delete_product_", "").split("_")
            category = parts[0]
            product_name = "_".join(parts[1:])  # Pour gérer les noms avec des underscores
        
            # Créer le clavier de confirmation
            keyboard = [
                [
                    InlineKeyboardButton("✅ Oui, supprimer", 
                        callback_data=f"really_delete_product_{category}_{product_name}"),
                    InlineKeyboardButton("❌ Non, annuler", 
                        callback_data="cancel_delete_product")
                ]
            ]
        
            await query.message.edit_text(
                f"⚠️ *Êtes-vous sûr de vouloir supprimer le produit* `{product_name}` *?*\n\n"
                f"Cette action est irréversible !",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return SELECTING_PRODUCT_TO_DELETE
        
        except Exception as e:
            print(f"Erreur lors de la confirmation de suppression: {e}")
            return await show_admin_menu(update, context)

    elif query.data.startswith("really_delete_product_"):
        try:
            parts = query.data.replace("really_delete_product_", "").split("_")
            category = parts[0]
            product_name = "_".join(parts[1:])
        
            if category in CATALOG:
                CATALOG[category] = [p for p in CATALOG[category] if p['name'] != product_name]
                save_catalog(CATALOG)
                await query.message.edit_text(
                    f"✅ Le produit *{product_name}* a été supprimé avec succès !",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Retour au menu", callback_data="admin")
                    ]])
                )
            return CHOOSING
        
        except Exception as e:
            print(f"Erreur lors de la suppression du produit: {e}")
            return await show_admin_menu(update, context)

    elif query.data == "edit_contact":
        await query.message.edit_text(
            "📱 Veuillez entrer le nouveau nom d'utilisateur Telegram pour le contact (avec ou sans @):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit_contact")
            ]])
        )
        return WAITING_CONTACT_USERNAME

    # Boutons d'annulation
    elif query.data in ["cancel_add_category", "cancel_add_product", "cancel_delete_category", 
                       "cancel_delete_product", "cancel_edit_contact"]:
        return await show_admin_menu(update, context)

    elif query.data == "back_to_categories":
        if 'category_message_id' in context.user_data:
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=context.user_data['category_message_id'],
                    text=context.user_data['category_message_text'],
                    reply_markup=InlineKeyboardMarkup(context.user_data['category_message_reply_markup']),
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Erreur lors de la mise à jour du message des catégories: {e}")
        else:
            # Si le message n'existe pas, recréez-le
            keyboard = []
            for category in CATALOG.keys():
                    keyboard.append([InlineKeyboardButton(category, callback_data=f"view_{category}")])

            keyboard.append([InlineKeyboardButton("🔙 Retour à l'accueil", callback_data="back_to_home")])

            await query.edit_message_text(
                "📋 *Menu*\n\n"
                "Choisissez une catégorie pour voir les produits :",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    elif query.data == "skip_media":
        category = context.user_data.get('temp_product_category')
        if category:
            new_product = {
                'name': context.user_data.get('temp_product_name'),
                'price': context.user_data.get('temp_product_price'),
                'description': context.user_data.get('temp_product_description')
            }
            
            if category not in CATALOG:
                CATALOG[category] = []
            CATALOG[category].append(new_product)
            save_catalog(CATALOG)
            
            context.user_data.clear()
            return await show_admin_menu(update, context)

    elif query.data.startswith("product_"):
        _, category, product_name = query.data.split("_", 2)
        product = next((p for p in CATALOG[category] if p['name'] == product_name), None)

        if product:
            caption = f"📱 *{product['name']}*\n\n"
            caption += f"💰 *Prix:*\n{product['price']}\n\n"
            caption += f"📝 *Description:*\n{product['description']}"

            keyboard = [[InlineKeyboardButton("🔙 Retour à la catégorie", callback_data=f"view_{category}")]]

            if 'media' in product and product['media']:
                media_list = product['media']
                media_list = sorted(media_list, key=lambda x: x.get('order_index', 0))
                total_media = len(media_list)
                context.user_data['current_media_index'] = 0
                current_media = media_list[0]

                if total_media > 1:
                    keyboard.insert(0, [
                        InlineKeyboardButton("⬅️ Précédent", callback_data=f"prev_media_{category}_{product_name}"),
                        InlineKeyboardButton("➡️ Suivant", callback_data=f"next_media_{category}_{product_name}")
                    ])

                await query.message.delete()

                if current_media['media_type'] == 'photo':
                    message = await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=current_media['media_id'],
                        caption=caption,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                else:
                    message = await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=current_media['media_id'],
                        caption=caption,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                context.user_data['last_product_message_id'] = message.message_id
            else:
                await query.message.edit_text(
                    text=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

            # Incrémenter les stats du produit
            stats.increment_product_views(CATALOG, category, product_name)

    elif query.data.startswith("view_"):
        category = query.data.replace("view_", "")
        if category in CATALOG:
            products = CATALOG[category]
            text = f"*{category}*\n\n"
            keyboard = []
            for product in products:
                keyboard.append([InlineKeyboardButton(
                    product['name'],
                    callback_data=f"product_{category}_{product['name']}"
                )])
        
            keyboard.append([InlineKeyboardButton("🔙 Retour au menu", callback_data="show_categories")])
        
            try:
                if 'last_product_message_id' in context.user_data:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=context.user_data['last_product_message_id']
                    )
                    del context.user_data['last_product_message_id']
            
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id
                )
            
                message = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                context.user_data['category_message_id'] = message.message_id
                context.user_data['category_message_text'] = text
                context.user_data['category_message_reply_markup'] = keyboard
            
            except Exception as e:
                print(f"Erreur lors de la mise à jour du message des produits: {e}")
                message = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                context.user_data['category_message_id'] = message.message_id

            # Incrémenter les stats du produit
            stats.increment_product_views(CATALOG, category, product['name'])

    elif query.data.startswith(("next_media_", "prev_media_")):
            try:
                _, direction, category, product_name = query.data.split("_", 3)
                product = next((p for p in CATALOG[category] if p['name'] == product_name), None)

                if product and 'media' in product:
                    media_list = sorted(product['media'], key=lambda x: x.get('order_index', 0))
                    total_media = len(media_list)
                    current_index = context.user_data.get('current_media_index', 0)

                    # Navigation simple
                    if direction == "next":
                        current_index = current_index + 1
                        if current_index >= total_media:
                            current_index = 0
                    else:  # prev
                        current_index = current_index - 1
                        if current_index < 0:
                            current_index = total_media - 1

                    # Une seule fois !
                    context.user_data['current_media_index'] = current_index
                    current_media = media_list[current_index]

                    caption = f"📱 *{product['name']}*\n\n"
                    caption += f"💰 *Prix:*\n{product['price']}\n\n"
                    caption += f"📝 *Description:*\n{product['description']}"

                    keyboard = []
                    if total_media > 1:
                        keyboard.append([
                            InlineKeyboardButton("⬅️ Précédent", callback_data=f"prev_media_{category}_{product_name}"),
                            InlineKeyboardButton("➡️ Suivant", callback_data=f"next_media_{category}_{product_name}")
                        ])
                    keyboard.append([InlineKeyboardButton("🔙 Retour à la catégorie", callback_data=f"view_{category}")])

                    try:
                        await query.message.delete()
                    except Exception as e:
                        print(f"Erreur lors de la suppression du message: {e}")

                    if current_media['media_type'] == 'photo':
                        message = await context.bot.send_photo(
                            chat_id=query.message.chat_id,
                            photo=current_media['media_id'],
                            caption=caption,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                    else:  # video
                        message = await context.bot.send_video(
                            chat_id=query.message.chat_id,
                            video=current_media['media_id'],
                            caption=caption,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                    context.user_data['last_product_message_id'] = message.message_id

            except Exception as e:
                print(f"Erreur lors de la navigation des médias: {e}")
                await query.answer("Une erreur est survenue")

    elif query.data == "edit_product":
        keyboard = []
        for category in CATALOG.keys():
                keyboard.append([
                    InlineKeyboardButton(
                        category, 
                        callback_data=f"editcat_{category}"  # Raccourci ici
                    )
                ])
        keyboard.append([InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit")])
        
        await query.message.edit_text(
            "✏️ Sélectionnez la catégorie du produit à modifier:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECTING_CATEGORY

    elif query.data.startswith("editcat_"):  # Nouveau gestionnaire avec nom plus court
        category = query.data.replace("editcat_", "")
        products = CATALOG.get(category, [])
        
        keyboard = []
        for product in products:
            if isinstance(product, dict):
                # Créer un callback_data plus court
                callback_data = f"editp_{category}_{product['name']}"[:64]  # Limite à 64 caractères
                keyboard.append([
                    InlineKeyboardButton(product['name'], callback_data=callback_data)
                ])
        keyboard.append([InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit")])
        
        await query.message.edit_text(
            f"✏️ Sélectionnez le produit à modifier dans {category}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECTING_PRODUCT_TO_EDIT

    elif query.data.startswith("editp_"):
        try:
            _, category, product_name = query.data.split("_", 2)
            context.user_data['editing_category'] = category
            context.user_data['editing_product'] = product_name
            
            keyboard = [
                [InlineKeyboardButton("📝 Nom", callback_data="edit_name")],
                [InlineKeyboardButton("💰 Prix", callback_data="edit_price")],
                [InlineKeyboardButton("📝 Description", callback_data="edit_desc")],
                [InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit")]
            ]
            
            await query.message.edit_text(
                f"✏️ Que souhaitez-vous modifier pour *{product_name}* ?\n"
                "Sélectionnez un champ à modifier:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return EDITING_PRODUCT_FIELD
        except Exception as e:
            print(f"Erreur dans editp_: {e}")
            return await show_admin_menu(update, context)

    elif query.data in ["edit_name", "edit_price", "edit_desc"]:
        field_mapping = {
            "edit_name": "name",
            "edit_price": "price",
            "edit_desc": "description",
        }
        field = field_mapping[query.data]
        context.user_data['editing_field'] = field
        
        category = context.user_data.get('editing_category')
        product_name = context.user_data.get('editing_product')
        
        product = next((p for p in CATALOG[category] if p['name'] == product_name), None)
        
        if product:
            current_value = product.get(field, "Non défini")
            if field == 'media':
                await query.message.edit_text(
                    "📸 Envoyez une nouvelle photo ou vidéo pour ce produit:\n"
                    "(ou cliquez sur Annuler pour revenir en arrière)",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit")
                    ]])
                )
                return WAITING_PRODUCT_MEDIA
            else:
                field_names = {
                    'name': 'nom',
                    'price': 'prix',
                    'description': 'description'
                }
                await query.message.edit_text(
                    f"✏️ Modification du {field_names.get(field, field)}\n"
                    f"Valeur actuelle : {current_value}\n\n"
                    "Envoyez la nouvelle valeur :",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Annuler", callback_data="cancel_edit")
                    ]])
                )
                return WAITING_NEW_VALUE

    elif query.data == "cancel_edit":
        return await show_admin_menu(update, context)
                        
    elif query.data == "show_categories":
        keyboard = []
        # Créer uniquement les boutons de catégories
        for category in CATALOG.keys():
                keyboard.append([InlineKeyboardButton(category, callback_data=f"view_{category}")])

        # Ajouter uniquement le bouton retour à l'accueil
        keyboard.append([InlineKeyboardButton("🔙 Retour à l'accueil", callback_data="back_to_home")])

        try:
            message = await query.edit_message_text(
                "📋 *Menu*\n\n"
                "Choisissez une catégorie pour voir les produits :",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            context.user_data['menu_message_id'] = message.message_id
        except Exception as e:
            print(f"Erreur lors de la mise à jour du message des catégories: {e}")
            # Si la mise à jour échoue, recréez le message
            message = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="📋 *Menu*\n\n"
                     "Choisissez une catégorie pour voir les produits :",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            context.user_data['menu_message_id'] = message.message_id

    elif query.data == "back_to_home":
        chat_id = update.effective_chat.id

        # Nouveau clavier simplifié pour l'accueil
        keyboard = [
            [InlineKeyboardButton("📋 MENU", callback_data="show_categories")]
        ]

        # Ajouter le bouton admin si l'utilisateur est administrateur
        if str(update.effective_user.id) in ADMIN_IDS:
            keyboard.append([InlineKeyboardButton("🔧 Menu Admin", callback_data="admin")])

        # Ajouter les boutons de contact et canaux
        keyboard.extend([
            [
                InlineKeyboardButton("📞 Contact telegram", url=f"https://t.me/{CONFIG['contact_username']}"),
                InlineKeyboardButton("📝 Exemple bouton 1", url="https://www.google.fr/"),
            ],
            [InlineKeyboardButton("🥔 Exemple bouton 2", url="https://www.google.fr")]
        ])

        welcome_text = (
            "🌿 *Bienvenue sur mon bot test !* 🌿\n\n"
            "Ce bot est juste un bot MENU en TEST, vous pouvez voir les fonctionnalités UTILISATEUR.\n\n"
            "📋 Cliquez sur MENU pour voir les catégories"
        )

        try:
            # Mettre à jour le menu d'accueil existant au lieu d'en créer un nouveau
            if 'menu_message_id' in context.user_data:
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=context.user_data['menu_message_id'],
                        text=welcome_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    print(f"Erreur lors de la mise à jour du message d'accueil: {e}")
                    # Si la mise à jour échoue, recréez le message
                    menu_message = await context.bot.send_message(
                        chat_id=chat_id,
                        text=welcome_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    context.user_data['menu_message_id'] = menu_message.message_id
            else:
                menu_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=welcome_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                context.user_data['menu_message_id'] = menu_message.message_id

        except Exception as e:
            print(f"Erreur lors du retour à l'accueil: {e}")

        return CHOOSING

    elif query.data == "start_broadcast":
        if str(update.effective_user.id) not in ADMIN_IDS:
            await query.answer("❌ Vous n'êtes pas autorisé à utiliser cette fonction.")
            return CHOOSING
            
        await query.message.edit_text(
            "📢 *Mode Diffusion*\n\n"
            "Envoyez le message que vous souhaitez diffuser à tous les utilisateurs.\n"
            "Le message peut contenir du texte, des photos ou des vidéos.\n\n"
            "Pour annuler, cliquez sur Annuler.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data="cancel_broadcast")
            ]])
        )
        return WAITING_BROADCAST_MESSAGE

    elif query.data == "cancel_broadcast":
        return await show_admin_menu(update, context)

    elif query.data == "manage_users":
        active_users = context.bot_data.get('active_users', {})
        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = load_active_users()

        cleaned = await clean_inactive_users(context)

        # Créer le texte sans formatage spécial d'abord
        text = "👥 Gestion des utilisateurs\n\n"
        text += f"Utilisateurs actifs : {len(active_users)}\n"
        text += f"Utilisateurs nettoyés : {cleaned}\n\n"
        text += "Liste des utilisateurs actifs :\n"

        # Liste des utilisateurs (limité à 20)
        for user_id, user_data in list(active_users.items())[:20]:
            username = user_data.get('username', '')
            first_name = user_data.get('first_name', '')
            last_name = user_data.get('last_name', '')

            full_name = f"{first_name} {last_name}".strip() or "Nom inconnu"

            text += f"\n• {full_name}"
            if username:
                text += f" (@{username})"

        if len(active_users) > 20:
            text += f"\n... et {len(active_users) - 20} autres utilisateurs"

        keyboard = [
            [InlineKeyboardButton("🔄 Nettoyer la liste", callback_data="clean_users")],
            [InlineKeyboardButton("🔙 Retour", callback_data="admin")]
        ]

        # Envoyer le message sans parse_mode
        await query.message.edit_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "clean_users":
            try:
                # Afficher un message de chargement
                await query.answer("🔄 Vérification des utilisateurs...")
                initial_count = len(context.bot_data.get('active_users', {}))
                cleaned = await clean_inactive_users(context)
                final_count = len(context.bot_data.get('active_users', {}))
            
                text = "👥 Rapport de vérification\n\n"
                text += f"• Utilisateurs scannés : {initial_count}\n"
            
                if cleaned > 0:
                    text += f"• Utilisateurs supprimés : {cleaned}\n"
                    text += f"• Utilisateurs restants : {final_count}\n"
                else:
                    text += "✅ Tous les utilisateurs sont actifs !\n"
            
                text += "\nListe des utilisateurs :\n"
            
                # Liste des utilisateurs actifs
                active_users = context.bot_data.get('active_users', {})
                for user_id, user_data in list(active_users.items())[:20]:
                    username = user_data.get('username', '')
                    first_name = user_data.get('first_name', '')
                    last_name = user_data.get('last_name', '')
                
                    full_name = f"{first_name} {last_name}".strip() or "Nom inconnu"
                    text += f"\n• {full_name}"
                    if username:
                        text += f" (@{username})"
            
                if len(active_users) > 20:
                    text += f"\n... et {len(active_users) - 20} autres utilisateurs"
            
                keyboard = [
                    [InlineKeyboardButton("🔄 Vérifier à nouveau", callback_data="clean_users")],
                    [InlineKeyboardButton("🔙 Retour", callback_data="admin")]
                ]
            
                await query.message.edit_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            except Exception as e:
                print(f"[ERROR] Erreur lors du nettoyage : {e}")
                # Message de fallback en cas d'erreur
                await query.message.edit_text(
                    "Une erreur est survenue lors du nettoyage.\n"
                    "Veuillez réessayer plus tard.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Retour", callback_data="admin")
                    ]])
                )
            # Incrémenter les stats du produit
            stats.increment_product_views(CATALOG, category, product_name)

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler temporaire pour obtenir le file_id de l'image banner"""
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        CONFIG['banner_image'] = file_id
        # Sauvegarder dans config.json
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=4)
        await update.message.reply_text(
            f"✅ Image banner enregistrée!\nFile ID: {file_id}"
        )

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'envoi du message de broadcast"""
    if str(update.effective_user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ Vous n'êtes pas autorisé à utiliser cette fonction.")
        return CHOOSING

    try:
        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = load_active_users()
        
        active_users = context.bot_data['active_users']
        
        # Convertir en dictionnaire si c'est encore un set
        if isinstance(active_users, set):
            active_users = {user_id: {
                'username': None,
                'first_name': None,
                'last_name': None,
                'last_seen': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            } for user_id in active_users}
            context.bot_data['active_users'] = active_users
        
        if not active_users:
            await update.message.reply_text(
                "❌ Aucun utilisateur actif trouvé.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Retour au menu admin", callback_data="admin")
                ]])
            )
            return CHOOSING

        success_count = 0
        fail_count = 0
        users_to_remove = set()  # Utiliser un set pour stocker les IDs à supprimer
        
        # Envoyer le message à chaque utilisateur
        for user_id in list(active_users.keys()):
            try:
                if update.message.photo:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=update.message.photo[-1].file_id,
                        caption=update.message.caption if update.message.caption else None,
                        parse_mode='Markdown'
                    )
                elif update.message.video:
                    await context.bot.send_video(
                        chat_id=user_id,
                        video=update.message.video.file_id,
                        caption=update.message.caption if update.message.caption else None,
                        parse_mode='Markdown'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=update.message.text,
                        parse_mode='Markdown'
                    )
                success_count += 1
                # Mettre à jour la dernière activité
                active_users[user_id]['last_seen'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"Erreur d'envoi à {user_id}: {e}")
                fail_count += 1
                if "bot was blocked" in str(e).lower() or "chat not found" in str(e).lower():
                    users_to_remove.add(user_id)

        # Supprimer les utilisateurs inactifs
        for user_id in users_to_remove:
            del active_users[user_id]
        
        # Sauvegarder les changements
        save_active_users(active_users)

        # Envoyer le rapport
        report = (
            "📊 *Rapport de diffusion*\n\n"
            f"✅ Envois réussis : {success_count}\n"
            f"❌ Échecs : {fail_count}\n"
            f"📨 Total : {success_count + fail_count}\n\n"
            f"👥 Utilisateurs actifs restants : {len(active_users)}"
        )
        
        await update.message.reply_text(
            report,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Retour au menu admin", callback_data="admin")
            ]])
        )
        
    except Exception as e:
        print(f"Erreur lors du broadcast: {e}")
        await update.message.reply_text(
            f"❌ Une erreur est survenue : {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Retour au menu admin", callback_data="admin")
            ]])
        )
    
    return CHOOSING

async def clean_inactive_users(context: ContextTypes.DEFAULT_TYPE):
    """Nettoie la liste des utilisateurs inactifs"""
    if 'active_users' not in context.bot_data:
        context.bot_data['active_users'] = load_active_users()
    
    active_users = context.bot_data['active_users'].copy()  # Créer une copie pour éviter les modifications pendant l'itération
    inactive_users = set()
    
    print(f"[DEBUG] Début du nettoyage - {datetime.utcnow()}")
    print(f"[DEBUG] Utilisateurs actuels: {len(active_users)}")
    
    for user_id in list(active_users.keys()):
        try:
            print(f"[DEBUG] Vérification de l'utilisateur {user_id}")
            
            # Première tentative : send_chat_action
            try:
                await context.bot.send_chat_action(chat_id=user_id, action="typing")
                await asyncio.sleep(0.1)  # Petit délai
            except Exception as e:
                print(f"[DEBUG] Échec send_chat_action pour {user_id}: {str(e)}")
                if "blocked" in str(e).lower() or "not found" in str(e).lower() or "deactivated" in str(e).lower():
                    raise  # Forcer le passage au except externe
                
            # Deuxième tentative : get_chat
            try:
                chat = await context.bot.get_chat(user_id)
                active_users[user_id] = {
                    'username': chat.username,
                    'first_name': chat.first_name,
                    'last_name': chat.last_name,
                    'last_seen': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                }
                print(f"[DEBUG] Utilisateur {user_id} actif et mis à jour")
            except Exception as e:
                print(f"[DEBUG] Échec get_chat pour {user_id}: {str(e)}")
                raise  # Forcer le passage au except externe
                
        except Exception as e:
            print(f"[DEBUG] Utilisateur {user_id} marqué comme inactif: {str(e)}")
            inactive_users.add(user_id)
            print(f"[DEBUG] Utilisateur {user_id} marqué comme inactif")
            print(f"[DEBUG] Raison : {str(e)}")
        
        await asyncio.sleep(0.2)  # Délai entre chaque utilisateur
    
    # Supprimer les utilisateurs inactifs
    users_removed = 0
    for user_id in inactive_users:
        if user_id in active_users:
            print(f"[DEBUG] Suppression de l'utilisateur {user_id}")
            del active_users[user_id]
            users_removed += 1
    
    # Mettre à jour context.bot_data
    context.bot_data['active_users'] = active_users
    save_active_users(active_users)
    
    print(f"[DEBUG] Fin du nettoyage - Utilisateurs restants: {len(active_users)}")
    print(f"[DEBUG] Utilisateurs supprimés: {users_removed}")
    
    return users_removed

async def back_to_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Nouveau clavier simplifié pour l'accueil
    keyboard = [
        [InlineKeyboardButton("📋 MENU", callback_data="show_categories")]
    ]

    # Ajouter le bouton admin si l'utilisateur est administrateur
    if str(update.effective_user.id) in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔧 Menu Admin", callback_data="admin")])

    # Ajouter les boutons de contact et canaux
    keyboard.extend([
        [
            InlineKeyboardButton("📞 Contact telegram", url=f"https://t.me/{CONFIG['contact_username']}"),
            InlineKeyboardButton("📝 Exemple bouton 1", url="https://www.google.fr/"),
        ],
        [InlineKeyboardButton("🥔 Exemple bouton 2", url="https://www.google.fr")]
    ])

    welcome_text = (
        "🌿 *Bienvenue sur mon bot test !* 🌿\n\n"
        "Ce bot est juste un bot MENU en TEST, vous pouvez voir les fonctionnalités UTILISATEUR.\n\n"
        "📋 Cliquez sur MENU pour voir les catégories"
    )

    try:
        # Mettre à jour le menu d'accueil existant au lieu d'en créer un nouveau
        if 'menu_message_id' in context.user_data:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=context.user_data['menu_message_id'],
                    text=welcome_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Erreur lors de la mise à jour du message d'accueil: {e}")
                # Si la mise à jour échoue, recréez le message
                menu_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=welcome_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                context.user_data['menu_message_id'] = menu_message.message_id
        else:
            menu_message = await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            context.user_data['menu_message_id'] = menu_message.message_id

    except Exception as e:
        print(f"Erreur lors du retour à l'accueil: {e}")

    return CHOOSING

def main():
    """Fonction principale du bot"""
    try:
        # Créer l'application
        application = Application.builder().token(TOKEN).build()

        # Gestionnaire de conversation principal
        conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('admin', admin),
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_CATEGORY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_category_name),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_PRODUCT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_name),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_PRODUCT_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_price),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_PRODUCT_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_description),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_PRODUCT_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO, handle_product_media),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            SELECTING_CATEGORY: [
                CallbackQueryHandler(handle_normal_buttons),
            ],
            SELECTING_CATEGORY_TO_DELETE: [
                CallbackQueryHandler(handle_normal_buttons),
            ],
            SELECTING_PRODUCT_TO_DELETE: [
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_CONTACT_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_contact_username),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            SELECTING_PRODUCT_TO_EDIT: [
                CallbackQueryHandler(handle_normal_buttons),
            ],
            EDITING_PRODUCT_FIELD: [
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_NEW_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_value),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_BANNER_IMAGE: [
                MessageHandler(filters.PHOTO, handle_banner_image),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_PRODUCT_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO, handle_product_media),
                CallbackQueryHandler(finish_product_media, pattern="^finish_media$"),
                CallbackQueryHandler(handle_normal_buttons),
            ],
            WAITING_BROADCAST_MESSAGE: [
    MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND,  # Parenthèses corrigées
        handle_broadcast_message
    ),
    CallbackQueryHandler(
        lambda u, c: show_admin_menu(u, c),
        pattern="cancel_broadcast"
    ),
],
         
        },
        fallbacks=[
            CommandHandler('start', start),
            CommandHandler('admin', admin),
        ],
        name="main_conversation",
        persistent=False,
    )
    
        application.add_handler(conv_handler)
        application.job_queue.run_daily(daily_maintenance, time=time(hour=0, minute=0))
        # Démarrer le bot
        print("Bot démarré...")
        application.run_polling()

    except Exception as e:
        print(f"Erreur lors du démarrage du bot: {e}")

if __name__ == '__main__':
    main()
