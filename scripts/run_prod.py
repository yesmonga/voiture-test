#!/usr/bin/env python3
"""
Runner Production - Point d'entrée unique pour le bot
Usage:
    python scripts/run_prod.py           # Run une fois
    python scripts/run_prod.py --loop    # Run en boucle (toutes les 15 min)
    python scripts/run_prod.py --dry-run # Pas de notifications
"""

import asyncio
import argparse
import sys
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_settings, BASE_DIR
from models.enums import Source
from services.orchestrator import Orchestrator, PipelineStats

# Import directly to avoid legacy __init__.py chain
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "autoscout24_v2", 
    Path(__file__).parent.parent / "scrapers" / "autoscout24_v2.py"
)
_autoscout_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_autoscout_module)

AutoScout24IndexScraper = _autoscout_module.AutoScout24IndexScraper
AutoScout24DetailScraper = _autoscout_module.AutoScout24DetailScraper
AutoScout24Config = _autoscout_module.AutoScout24Config


# Stats de blocage (persistées entre runs)
class RunnerStats:
    """Stats du runner pour observabilité"""
    
    def __init__(self):
        self.total_runs = 0
        self.total_listings = 0
        self.total_notifications = 0
        self.consecutive_zero_listings = 0
        self.blocked_count = 0
        self.error_count = 0
        self.last_run: Optional[datetime] = None
        self.last_error: Optional[str] = None
    
    def record_run(self, stats: PipelineStats):
        self.total_runs += 1
        self.total_listings += stats.index_scanned
        self.total_notifications += stats.notified
        self.last_run = datetime.now(timezone.utc)
        
        if stats.index_scanned == 0:
            self.consecutive_zero_listings += 1
        else:
            self.consecutive_zero_listings = 0
    
    def record_error(self, error: str):
        self.error_count += 1
        self.last_error = error
    
    def record_blocked(self):
        self.blocked_count += 1
    
    def summary(self) -> str:
        return (
            f"Runs: {self.total_runs} | "
            f"Listings: {self.total_listings} | "
            f"Notifs: {self.total_notifications} | "
            f"Blocked: {self.blocked_count} | "
            f"Errors: {self.error_count} | "
            f"Zero streak: {self.consecutive_zero_listings}"
        )


def load_searches_config() -> dict:
    """Charge la configuration des recherches depuis YAML"""
    config_path = BASE_DIR / "config" / "searches.yaml"
    
    if not config_path.exists():
        print(f"❌ Config not found: {config_path}")
        sys.exit(1)
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_scraper_from_config(search_config: dict) -> tuple:
    """Crée un scraper à partir de la config"""
    source = search_config.get("source", "").lower()
    
    if source == "autoscout24":
        config = AutoScout24Config(
            marque=search_config.get("marque", "").lower(),
            modele=search_config.get("modele", ""),
            prix_min=search_config.get("prix_min", 0),
            prix_max=search_config.get("prix_max", 2000),
            km_min=search_config.get("km_min", 0),  # Support km_min
            km_max=search_config.get("km_max", 180000),
            annee_min=search_config.get("annee_min", 2006),
            annee_max=search_config.get("annee_max", 2014),
            carburant=search_config.get("carburant", "diesel"),
            zip_code=search_config.get("zip_code", ""),
            radius_km=search_config.get("radius_km", 0),
            particulier_only=search_config.get("particulier_only", True),
        )
        return (
            AutoScout24IndexScraper(config),
            AutoScout24DetailScraper(),
            Source.AUTOSCOUT24,
            search_config,
        )
    else:
        raise ValueError(f"Source non supportée: {source}")


async def send_alert_notification(message: str):
    """Envoie une alerte Discord (blocage, erreur, etc.)"""
    try:
        from services.notifier.discord import _get_webhook_url
        import httpx
        
        webhook_url = _get_webhook_url()
        if not webhook_url:
            print(f"⚠️ Alert (no webhook): {message}")
            return
        
        async with httpx.AsyncClient() as client:
            await client.post(webhook_url, json={
                "content": f"🚨 **ALERT BOT VOITURES**\n{message}"
            })
        print(f"📢 Alert sent: {message}")
    except Exception as e:
        print(f"⚠️ Failed to send alert: {e}")


async def run_single_search(
    orch: Orchestrator,
    search_config: dict,
    runner_config: dict,
    dry_run: bool = False,
) -> PipelineStats:
    """Exécute une recherche unique"""
    name = search_config.get("name", "unknown")
    source = search_config.get("source", "").lower()
    
    print(f"\n{'='*50}")
    print(f"🔍 Search: {name}")
    print(f"   Source: {source}")
    print(f"   {search_config.get('marque')} {search_config.get('modele')}")
    print(f"   Prix: {search_config.get('prix_min')}-{search_config.get('prix_max')}€")
    
    # Créer le scraper
    index_scraper, detail_scraper, source_enum, cfg = create_scraper_from_config(search_config)
    
    # Passer marque/modele au scraper pour fallback
    index_scraper._fallback_marque = cfg.get("marque", "")
    index_scraper._fallback_modele = cfg.get("modele", "")
    
    orch.register_scraper(source_enum, index_scraper, detail_scraper)
    
    try:
        stats = await orch.run_pipeline(
            sources=[source_enum],
            detail_threshold=search_config.get("detail_threshold", 30),
            notify_threshold=search_config.get("notify_threshold", 60) if not dry_run else 999,
            max_detail_per_run=runner_config.get("max_detail_per_run", 10),
            max_pages=search_config.get("max_pages", 1),
        )
        
        print(f"   Result: {stats.summary()}")
        return stats
        
    finally:
        await index_scraper.close()
        await detail_scraper.close()


async def run_all_searches(dry_run: bool = False) -> tuple[list[PipelineStats], RunnerStats]:
    """Exécute toutes les recherches activées"""
    config = load_searches_config()
    searches = config.get("searches", [])
    runner_config = config.get("runner", {})
    
    enabled_searches = [s for s in searches if s.get("enabled", True)]
    
    print(f"\n{'#'*50}")
    print(f"# VOITURES BOT - Production Run")
    print(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"# Searches: {len(enabled_searches)} enabled")
    print(f"# Dry run: {dry_run}")
    print(f"{'#'*50}")
    
    runner_stats = RunnerStats()
    all_stats: list[PipelineStats] = []
    
    orch = Orchestrator()
    
    for i, search in enumerate(enabled_searches):
        try:
            stats = await run_single_search(orch, search, runner_config, dry_run)
            all_stats.append(stats)
            runner_stats.record_run(stats)
            
            # Pause entre les recherches
            if i < len(enabled_searches) - 1:
                delay = runner_config.get("delay_between_searches_sec", 5)
                print(f"\n⏳ Pause {delay}s before next search...")
                await asyncio.sleep(delay)
                
        except Exception as e:
            print(f"❌ Error in search '{search.get('name')}': {e}")
            runner_stats.record_error(str(e))
    
    # Alertes
    if runner_config.get("alert_on_zero_listings", True):
        threshold = runner_config.get("zero_listings_threshold", 3)
        if runner_stats.consecutive_zero_listings >= threshold:
            await send_alert_notification(
                f"⚠️ 0 listings pendant {runner_stats.consecutive_zero_listings} runs consécutifs!\n"
                "Possible blocage ou changement de structure HTML."
            )
    
    # Résumé
    print(f"\n{'='*50}")
    print(f"📊 RUN SUMMARY")
    print(f"   {runner_stats.summary()}")
    
    total_new = sum(s.index_new for s in all_stats)
    total_detail = sum(s.detail_fetched for s in all_stats)
    total_notif = sum(s.notified for s in all_stats)
    
    print(f"   New: {total_new} | Detail: {total_detail} | Notified: {total_notif}")
    print(f"{'='*50}\n")
    
    return all_stats, runner_stats


def get_jittered_interval(base_sec: int, jitter_sec: int) -> float:
    """Retourne un intervalle avec jitter aléatoire"""
    import random
    return base_sec + random.uniform(-jitter_sec, jitter_sec)


async def run_loop(interval_sec: int = 60, dry_run: bool = False):
    """
    Exécute en boucle avec intervalle + jitter + backoff.
    
    Args:
        interval_sec: Intervalle de base en secondes (default 60s)
        dry_run: Pas de notifications si True
    """
    config = load_searches_config()
    defaults = config.get("defaults", {})
    
    base_interval = defaults.get("scan_interval_sec", interval_sec)
    jitter = defaults.get("jitter_sec", 10)
    backoff_mult = defaults.get("backoff_multiplier", 2)
    backoff_max = defaults.get("backoff_max_sec", 300)
    
    print(f"🔄 Starting loop mode")
    print(f"   Base interval: {base_interval}s (±{jitter}s jitter)")
    print(f"   Backoff: x{backoff_mult} (max {backoff_max}s)")
    print(f"   Press Ctrl+C to stop\n")
    
    running = True
    current_backoff = 0
    consecutive_errors = 0
    
    def signal_handler(sig, frame):
        nonlocal running
        print("\n⏹️ Stopping loop...")
        running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    while running:
        try:
            all_stats, runner_stats = await run_all_searches(dry_run)
            
            # Reset backoff on success
            if runner_stats.consecutive_zero_listings < 3:
                current_backoff = 0
                consecutive_errors = 0
            else:
                # Possible blocage, augmenter backoff
                current_backoff = min(
                    current_backoff * backoff_mult if current_backoff else base_interval,
                    backoff_max
                )
                print(f"⚠️ Possible blocage, backoff: {current_backoff}s")
                
        except Exception as e:
            print(f"❌ Run failed: {e}")
            consecutive_errors += 1
            current_backoff = min(
                current_backoff * backoff_mult if current_backoff else base_interval,
                backoff_max
            )
            if consecutive_errors >= 3:
                await send_alert_notification(f"Run failed {consecutive_errors}x: {e}")
        
        if running:
            # Intervalle avec jitter + backoff éventuel
            sleep_time = get_jittered_interval(base_interval, jitter) + current_backoff
            print(f"💤 Next scan in {sleep_time:.0f}s...")
            
            # Sleep interruptible
            for _ in range(int(sleep_time)):
                if not running:
                    break
                await asyncio.sleep(1)
    
    print("👋 Loop stopped")


def main():
    parser = argparse.ArgumentParser(description="Voitures Bot - Production Runner")
    parser.add_argument("--loop", action="store_true", help="Run in loop mode")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval in seconds (default 60)")
    parser.add_argument("--dry-run", action="store_true", help="No notifications")
    parser.add_argument("--search", type=str, help="Run specific search only")
    
    args = parser.parse_args()
    
    if args.loop:
        asyncio.run(run_loop(args.interval, args.dry_run))
    else:
        all_stats, runner_stats = asyncio.run(run_all_searches(args.dry_run))
        
        # Exit code basé sur les erreurs
        if runner_stats.error_count > 0:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()
