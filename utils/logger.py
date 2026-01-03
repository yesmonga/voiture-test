"""
Logger - Configuration du logging
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from rich.logging import RichHandler
from rich.console import Console

from config import LOG_LEVEL, DEBUG


console = Console()

# Créer le répertoire logs
Path("logs").mkdir(exist_ok=True)


def setup_logger(name: str = "voitures_bot") -> logging.Logger:
    """Configure et retourne un logger"""
    
    logger = logging.getLogger(name)
    
    # Éviter les doublons de handlers
    if logger.handlers:
        return logger
    
    level = logging.DEBUG if DEBUG else getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)
    
    # Handler console avec Rich
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True
    )
    console_handler.setLevel(level)
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    
    # Handler fichier
    log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = "voitures_bot") -> logging.Logger:
    """Retourne un logger existant ou en crée un nouveau"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# Logger principal
logger = setup_logger()


def log_annonce(annonce, action: str = "trouvée"):
    """Log une annonce de manière formatée"""
    emoji = annonce.emoji_alerte
    logger.info(
        f"{emoji} Annonce {action}: {annonce.marque} {annonce.modele} - "
        f"{annonce.prix}€ - {annonce.kilometrage}km - Score: {annonce.score_rentabilite}/100 - "
        f"{annonce.source}"
    )


def log_scraping_start(source: str):
    """Log le début d'un scraping"""
    logger.info(f"🔍 Démarrage scraping {source}...")


def log_scraping_end(source: str, count: int, new_count: int):
    """Log la fin d'un scraping"""
    logger.info(f"✅ Scraping {source} terminé: {count} annonces trouvées, {new_count} nouvelles")


def log_notification(annonce, channel: str):
    """Log l'envoi d'une notification"""
    logger.info(f"📤 Notification envoyée via {channel}: {annonce.marque} {annonce.modele}")


def log_error(message: str, exc: Exception = None):
    """Log une erreur"""
    if exc:
        logger.error(f"❌ {message}: {exc}", exc_info=True)
    else:
        logger.error(f"❌ {message}")
