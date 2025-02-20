#!/usr/bin/env python3
import os
import re
import yt_dlp
import asyncio
import subprocess
import json
import random
import requests
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
)

# Initialisation de la journalisation
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Variables de configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("Le jeton Telegram (TELEGRAM_BOT_TOKEN) n'est pas défini.")
    exit(1)

ADMIN_ID = 6744885896
USER_PREFERENCES_FILE = "user_preferences.json"
ALLOWED_USERS_FILE = "allowed_users.json"
SAVE_DIRECTORY = "allsauvegard"
DOWNLOADS_DIRECTORY = os.path.join(SAVE_DIRECTORY, "downloads")

# Création des répertoires nécessaires
os.makedirs(SAVE_DIRECTORY, exist_ok=True)
os.makedirs(DOWNLOADS_DIRECTORY, exist_ok=True)

# Fonctions utilitaires pour la gestion des utilisateurs
def load_json_file(file_path, default):
    """Charge un fichier JSON ou retourne une valeur par défaut."""
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de décodage JSON dans {file_path}: {e}")
    return default


def save_json_file(file_path, data):
    """Sauvegarde des données dans un fichier JSON."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde dans {file_path}: {e}")


USER_PREFERENCES = load_json_file(USER_PREFERENCES_FILE, {})
ALLOWED_USERS = load_json_file(ALLOWED_USERS_FILE, [])

# Vérification des dépendances (FFmpeg requis)
def check_dependencies():
    """Vérifie si FFmpeg est installé."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
    except FileNotFoundError:
        logger.error("FFmpeg n'est pas installé. Veuillez l'installer pour continuer.")
        exit(1)
    except subprocess.CalledProcessError as e:
        logger.error(f"Erreur lors de la vérification de FFmpeg: {e}")
        exit(1)


# Classe principale du bot
class TikTokBot:
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self.executor = ThreadPoolExecutor(max_workers=5)  # Téléchargements multi-thread
        self.register_handlers()

    def register_handlers(self):
        """Enregistre les commandes et gestionnaires de messages."""
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("admin", self.admin))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_link))
        self.app.add_handler(CallbackQueryHandler(self.handle_user_choice))

    async def start(self, update: Update, context: CallbackContext):
        """Message d'accueil pour l'utilisateur."""
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name or "Utilisateur"
        if user_id == ADMIN_ID:
            message = f"👑 Bonjour Admin {first_name}, ravi de vous revoir !"
        else:
            if user_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(user_id)
                save_json_file(ALLOWED_USERS_FILE, ALLOWED_USERS)
            messages = [
                f"Salut {first_name} ! 😊",
                f"Bienvenue {first_name} ! 😃",
                "Heureux de vous voir ici ! 👍",
            ]
            message = random.choice(messages)
        await update.message.reply_text(message)

    async def help(self, update: Update, context: CallbackContext):
        """Affiche le message d'aide."""
        help_text = (
            "📚 **Comment utiliser le bot TikTok** :\n\n"
            "1️⃣ Envoyez un lien TikTok.\n"
            "2️⃣ Choisissez ce que vous voulez télécharger : Vidéo, Audio, ou Images.\n\n"
            "🎛 **Commandes disponibles** :\n"
            "/help - Affiche ce message.\n"
            "/admin - Gestion des utilisateurs autorisés (admin uniquement).\n"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def admin(self, update: Update, context: CallbackContext):
        """Gestion des utilisateurs autorisés (réservé à l'admin)."""
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Accès réservé à l'administrateur.")
            return

        args = context.args
        if not args:
            msg = "📋 **Utilisateurs autorisés actuels** :\n" + "\n".join(
                [f"- {u}" for u in ALLOWED_USERS]
            )
            msg += (
                "\n\n⚙️ **Commandes admin** :\n"
                "/admin add <user_id> - Ajouter un utilisateur.\n"
                "/admin remove <user_id> - Retirer un utilisateur."
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            command = args[0].lower()
            if command == "add" and len(args) == 2:
                try:
                    new_id = int(args[1])
                    if new_id not in ALLOWED_USERS:
                        ALLOWED_USERS.append(new_id)
                        save_json_file(ALLOWED_USERS_FILE, ALLOWED_USERS)
                        await update.message.reply_text(f"✅ Utilisateur {new_id} ajouté.")
                    else:
                        await update.message.reply_text("⚠️ L'utilisateur est déjà autorisé.")
                except ValueError:
                    await update.message.reply_text("❌ ID utilisateur invalide.")
            elif command == "remove" and len(args) == 2:
                try:
                    rem_id = int(args[1])
                    if rem_id in ALLOWED_USERS:
                        ALLOWED_USERS.remove(rem_id)
                        save_json_file(ALLOWED_USERS_FILE, ALLOWED_USERS)
                        await update.message.reply_text(f"✅ Utilisateur {rem_id} retiré.")
                    else:
                        await update.message.reply_text("⚠️ L'utilisateur n'est pas dans la liste.")
                except ValueError:
                    await update.message.reply_text("❌ ID utilisateur invalide.")
            else:
                await update.message.reply_text("❌ Commande admin invalide.")

    async def handle_link(self, update: Update, context: CallbackContext):
        """Gestion des liens envoyés par l'utilisateur."""
        user_id = update.effective_user.id
        if user_id != ADMIN_ID and user_id not in ALLOWED_USERS:
            await update.message.reply_text("❌ Accès refusé.")
            return

        url = update.message.text.strip()
        if not self.is_tiktok_url(url):
            await update.message.reply_text("❌ Lien TikTok invalide.")
            return

        # Détection du type de média (vidéo ou image)
        media_type = await asyncio.to_thread(self.detect_tiktok_media_type, url)
        if media_type == "video":
            buttons = [
                [InlineKeyboardButton("Vidéo HD", callback_data=f"video_hd|{url}"),
                 InlineKeyboardButton("Audio (MP3)", callback_data=f"audio|{url}")]
            ]
        elif media_type == "image":
            buttons = [[InlineKeyboardButton("Télécharger Images", callback_data=f"image|{url}")]]
        else:
            await update.message.reply_text("❌ Impossible de détecter le type de média.")
            return

        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "🎥 Que voulez-vous télécharger ?", reply_markup=reply_markup
        )

    async def handle_user_choice(self, update: Update, context: CallbackContext):
        """Gère les choix de téléchargement de l'utilisateur."""
        query = update.callback_query
        await query.answer()
        try:
            choice, url = query.data.split("|", 1)
        except ValueError:
            await query.edit_message_text("❌ Données de callback invalides.")
            return

        # Téléchargement selon le choix
        if choice == "video_hd":
            video_path = await asyncio.to_thread(self.download_tiktok_video, url, high_quality=True)
            if video_path:
                await self.send_file(query, video_path, "video")
        elif choice == "audio":
            audio_path = await asyncio.to_thread(self.download_tiktok_audio, url)
            if audio_path:
                await self.send_file(query, audio_path, "audio")

    async def send_file(self, query, file_path, file_type):
        """Envoie un fichier téléchargé à l'utilisateur."""
        try:
            with open(file_path, "rb") as file:
                if file_type == "video":
                    await query.message.reply_video(video=file)
                elif file_type == "audio":
                    await query.message.reply_audio(audio=file)
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du fichier : {e}")
        finally:
            os.remove(file_path)

    def is_tiktok_url(self, url: str) -> bool:
        """Vérifie si l'URL est un lien TikTok valide."""
        return re.search(r"(https?://)?(www\.)?(vm\.tiktok\.com|tiktok\.com)/", url) is not None

    def detect_tiktok_media_type(self, url: str) -> str:
        """Détecte automatiquement si le lien pointe vers une vidéo ou une image."""
        try:
            ydl_opts = {"quiet": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if "formats" in info:
                    return "video"
                if "thumbnails" in info:
                    return "image"
        except Exception as e:
            logger.error(f"Erreur lors de la détection du média : {e}")
        return None

    def download_tiktok_video(self, url: str, high_quality=False) -> str:
        """Télécharge une vidéo TikTok avec option haute qualité."""
        filename = os.path.join(DOWNLOADS_DIRECTORY, f"video_{uuid.uuid4()}.mp4")
        ydl_opts = {
            "outtmpl": filename,
            "quiet": True,
            "format": "bestvideo+bestaudio/best" if high_quality else "best",
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return filename if os.path.exists(filename) else None
        except Exception as e:
            logger.error(f"Erreur lors du téléchargement de la vidéo : {e}")
        return None

    def download_tiktok_audio(self, url: str) -> str:
        """Télécharge l'audio d'une vidéo TikTok."""
        filename = os.path.join(DOWNLOADS_DIRECTORY, f"audio_{uuid.uuid4()}.mp3")
        ydl_opts = {"format": "bestaudio/best", "outtmpl": filename, "quiet": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return filename if os.path.exists(filename) else None
        except Exception as e:
            logger.error(f"Erreur lors du téléchargement de l'audio : {e}")
        return None

    def run(self):
        """Démarre le bot."""
        logger.info("🚀 Démarrage du bot...")
        self.app.run_polling()


if __name__ == "__main__":
    check_dependencies()
    bot = TikTokBot(TOKEN)
    bot.run()
