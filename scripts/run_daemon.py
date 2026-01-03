#!/usr/bin/env python3
"""
Run Daemon - Runner production avec logs persistants et alertes
Usage:
    python scripts/run_daemon.py              # Run en boucle
    python scripts/run_daemon.py --once       # Run une fois
    python scripts/run_daemon.py --dry-run    # Sans notifications
"""

import asyncio
import argparse
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import BASE_DIR, DATA_DIR
from scripts.run_prod_v2 import run_all_searches, run_loop, load_searches_config

# === Logging Setup ===
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

def setup_logging(verbose: bool = False):
    """Configure le logging avec rotation"""
    log_file = LOG_DIR / "voitures-bot.log"
    
    # Format
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # File handler avec rotation (10MB, 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Réduire le bruit des libs externes
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    return logging.getLogger("voitures-bot")


async def send_startup_notification():
    """Envoie une notification au démarrage"""
    import httpx
    
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    
    config = load_searches_config()
    searches = [s["name"] for s in config.get("searches", []) if s.get("enabled", True)]
    
    message = {
        "embeds": [{
            "title": "🚗 Voitures Bot Démarré",
            "description": f"Recherches actives: {', '.join(searches)}",
            "color": 0x00FF00,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json=message)
    except Exception as e:
        print(f"⚠️ Startup notification failed: {e}")


async def send_shutdown_notification(reason: str = "Manual stop"):
    """Envoie une notification à l'arrêt"""
    import httpx
    
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    
    message = {
        "embeds": [{
            "title": "🛑 Voitures Bot Arrêté",
            "description": f"Raison: {reason}",
            "color": 0xFF0000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json=message)
    except Exception:
        pass


async def send_zero_listings_alert(consecutive_count: int, sources: list[str]):
    """Alerte si 0 annonces pendant plusieurs runs"""
    import httpx
    
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    
    message = {
        "embeds": [{
            "title": "⚠️ Alerte: 0 Annonces",
            "description": f"0 annonces pendant {consecutive_count} runs consécutifs.\nSources: {', '.join(sources)}\nPossible blocage ou problème de parsing.",
            "color": 0xFFA500,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json=message)
    except Exception:
        pass


async def run_daemon(dry_run: bool = False, once: bool = False, verbose: bool = False):
    """Run principal du daemon"""
    logger = setup_logging(verbose)
    logger.info("=" * 60)
    logger.info("VOITURES BOT DAEMON - Starting")
    logger.info(f"Dry run: {dry_run} | Once: {once}")
    logger.info("=" * 60)
    
    # Notification démarrage
    if not dry_run:
        await send_startup_notification()
    
    consecutive_zero = 0
    running = True
    
    def handle_signal(sig, frame):
        nonlocal running
        logger.info(f"Signal {sig} reçu, arrêt en cours...")
        running = False
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        if once:
            # Run unique
            all_stats, runner_stats = await run_all_searches(dry_run)
            logger.info(f"Run terminé: {runner_stats.summary()}")
        else:
            # Run en boucle
            config = load_searches_config()
            defaults = config.get("defaults", {})
            interval = defaults.get("scan_interval_sec", 60)
            jitter = defaults.get("jitter_sec", 10)
            
            logger.info(f"Mode boucle: interval={interval}s, jitter=±{jitter}s")
            
            while running:
                try:
                    all_stats, runner_stats = await run_all_searches(dry_run)
                    logger.info(f"Run: {runner_stats.summary()}")
                    
                    # Vérifier zéro listings
                    if runner_stats.consecutive_zero_listings >= 3:
                        consecutive_zero += 1
                        if consecutive_zero == 1 or consecutive_zero % 5 == 0:
                            await send_zero_listings_alert(
                                runner_stats.consecutive_zero_listings,
                                list(runner_stats.by_source.keys())
                            )
                    else:
                        consecutive_zero = 0
                    
                except Exception as e:
                    logger.error(f"Erreur run: {e}", exc_info=True)
                
                if running:
                    import random
                    sleep_time = interval + random.uniform(-jitter, jitter)
                    logger.debug(f"Prochain scan dans {sleep_time:.0f}s")
                    
                    for _ in range(int(sleep_time)):
                        if not running:
                            break
                        await asyncio.sleep(1)
    
    except Exception as e:
        logger.error(f"Erreur daemon: {e}", exc_info=True)
        if not dry_run:
            await send_shutdown_notification(f"Error: {e}")
        raise
    
    finally:
        logger.info("VOITURES BOT DAEMON - Stopped")
        if not dry_run and not once:
            await send_shutdown_notification("Normal shutdown")


def main():
    parser = argparse.ArgumentParser(description="Voitures Bot Daemon")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true", help="No notifications")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    asyncio.run(run_daemon(
        dry_run=args.dry_run,
        once=args.once,
        verbose=args.verbose
    ))


if __name__ == "__main__":
    main()
