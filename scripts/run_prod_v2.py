#!/usr/bin/env python3
"""
Runner Production V2 - Multi-sources avec circuit breaker
Usage:
    python scripts/run_prod_v2.py           # Run une fois
    python scripts/run_prod_v2.py --loop    # Run en boucle (60s + jitter)
    python scripts/run_prod_v2.py --dry-run # Pas de notifications
"""

import asyncio
import argparse
import sys
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_settings, BASE_DIR
from models.enums import Source
from services.orchestrator import Orchestrator, PipelineStats
from scrapers.rate_limiter import get_rate_limiter

# Import des scrapers
from scrapers.autoscout24_v2 import (
    AutoScout24IndexScraper, AutoScout24DetailScraper, AutoScout24Config
)
from scrapers.lacentrale_v2 import (
    LaCentraleIndexScraper, LaCentraleDetailScraper, LaCentraleConfig
)
from scrapers.paruvendu_v2 import (
    ParuVenduIndexScraper, ParuVenduDetailScraper, ParuVenduConfig
)
from scrapers.leboncoin_v1 import (
    LeboncoinIndexScraper, LeboncoinDetailScraper, LeboncoinConfig
)
from scrapers.http_client import close_all_clients


@dataclass
class SourceStats:
    """Stats par source"""
    scanned: int = 0
    new: int = 0
    duplicates: int = 0
    blocked: int = 0
    errors: int = 0
    notified: int = 0


@dataclass
class RunnerStats:
    """Stats du runner pour observabilité"""
    total_runs: int = 0
    total_listings: int = 0
    total_notifications: int = 0
    consecutive_zero_listings: int = 0
    blocked_count: int = 0
    error_count: int = 0
    last_run: Optional[datetime] = None
    last_error: Optional[str] = None
    
    # Stats par source
    by_source: dict = field(default_factory=dict)
    
    def record_run(self, stats: PipelineStats):
        self.total_runs += 1
        self.total_listings += stats.index_scanned
        self.total_notifications += stats.notified
        self.last_run = datetime.now(timezone.utc)
        
        if stats.index_scanned == 0:
            self.consecutive_zero_listings += 1
        else:
            self.consecutive_zero_listings = 0
    
    def record_source_stats(self, source: str, scanned: int, new: int, 
                           duplicates: int, blocked: bool, errors: int, notified: int):
        if source not in self.by_source:
            self.by_source[source] = SourceStats()
        
        s = self.by_source[source]
        s.scanned += scanned
        s.new += new
        s.duplicates += duplicates
        s.blocked += 1 if blocked else 0
        s.errors += errors
        s.notified += notified
    
    def record_error(self, error: str):
        self.error_count += 1
        self.last_error = error
    
    def summary(self) -> str:
        return (
            f"Runs: {self.total_runs} | "
            f"Listings: {self.total_listings} | "
            f"Notifs: {self.total_notifications} | "
            f"Blocked: {self.blocked_count} | "
            f"Errors: {self.error_count} | "
            f"Zero streak: {self.consecutive_zero_listings}"
        )
    
    def source_summary(self) -> str:
        lines = []
        for source, s in self.by_source.items():
            lines.append(f"   {source}: {s.scanned} scanned, {s.new} new, {s.blocked} blocked")
        return "\n".join(lines)


def load_searches_config() -> dict:
    """Charge la configuration des recherches depuis YAML"""
    config_path = BASE_DIR / "config" / "searches.yaml"
    
    if not config_path.exists():
        print(f"❌ Config not found: {config_path}")
        sys.exit(1)
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_scrapers_for_source(source: str, search_config: dict) -> tuple:
    """Crée les scrapers pour une source donnée"""
    marque = search_config.get("marque", "").lower()
    modele = search_config.get("modele", "")
    prix_min = search_config.get("prix_min", 0)
    prix_max = search_config.get("prix_max", 2000)
    km_min = search_config.get("km_min", 0)
    km_max = search_config.get("km_max", 180000)
    annee_min = search_config.get("annee_min", 2006)
    annee_max = search_config.get("annee_max", 2014)
    carburant = search_config.get("carburant", "diesel")
    particulier_only = search_config.get("particulier_only", True)
    
    source_lower = source.lower()
    
    if source_lower == "autoscout24":
        config = AutoScout24Config(
            marque=marque,
            modele=modele,
            prix_min=prix_min,
            prix_max=prix_max,
            km_min=km_min,
            km_max=km_max,
            annee_min=annee_min,
            annee_max=annee_max,
            carburant=carburant,
            zip_code=search_config.get("zip_code", ""),
            radius_km=search_config.get("radius_km", 0),
            particulier_only=particulier_only,
        )
        index_scraper = AutoScout24IndexScraper(config)
        index_scraper._fallback_marque = search_config.get("marque", "")
        index_scraper._fallback_modele = modele
        return index_scraper, AutoScout24DetailScraper(), Source.AUTOSCOUT24
    
    elif source_lower == "lacentrale":
        config = LaCentraleConfig(
            marque=marque,
            modele=modele,
            prix_min=prix_min,
            prix_max=prix_max,
            km_min=km_min,
            km_max=km_max,
            annee_min=annee_min,
            annee_max=annee_max,
            carburant=carburant,
            particulier_only=particulier_only,
        )
        index_scraper = LaCentraleIndexScraper(config)
        index_scraper._fallback_marque = search_config.get("marque", "")
        index_scraper._fallback_modele = modele
        return index_scraper, LaCentraleDetailScraper(), Source.LACENTRALE
    
    elif source_lower == "paruvendu":
        config = ParuVenduConfig(
            marque=marque,
            modele=modele,
            prix_min=prix_min,
            prix_max=prix_max,
            km_min=km_min,
            km_max=km_max,
            annee_min=annee_min,
            annee_max=annee_max,
            carburant=carburant,
            particulier_only=particulier_only,
        )
        index_scraper = ParuVenduIndexScraper(config)
        index_scraper._fallback_marque = search_config.get("marque", "")
        index_scraper._fallback_modele = modele
        return index_scraper, ParuVenduDetailScraper(), Source.PARUVENDU
    
    elif source_lower == "leboncoin":
        config = LeboncoinConfig(
            marque=marque,
            modele=modele,
            prix_min=prix_min,
            prix_max=prix_max,
            km_min=km_min,
            km_max=km_max,
            annee_min=annee_min,
            annee_max=annee_max,
            carburant=carburant,
            particulier_only=particulier_only,
        )
        index_scraper = LeboncoinIndexScraper(config)
        index_scraper._fallback_marque = search_config.get("marque", "")
        index_scraper._fallback_modele = modele
        return index_scraper, LeboncoinDetailScraper(), Source.LEBONCOIN
    
    else:
        raise ValueError(f"Source non supportée: {source}")


async def send_alert_notification(message: str):
    """Envoie une alerte Discord"""
    try:
        import os
        import httpx
        
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
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


async def run_search_multi_source(
    search_config: dict,
    runner_config: dict,
    runner_stats: RunnerStats,
    dry_run: bool = False,
) -> PipelineStats:
    """Exécute une recherche sur plusieurs sources"""
    name = search_config.get("name", "unknown")
    
    # Récupérer les sources (nouveau format: liste, ancien format: string)
    sources = search_config.get("sources", [])
    if not sources:
        # Fallback ancien format
        single_source = search_config.get("source", "")
        if single_source:
            sources = [single_source]
    
    if not sources:
        print(f"⚠️ Search '{name}': aucune source configurée")
        return PipelineStats()
    
    print(f"\n{'='*60}")
    print(f"🔍 Search: {name}")
    print(f"   {search_config.get('marque')} {search_config.get('modele')}")
    print(f"   Prix: {search_config.get('prix_min')}-{search_config.get('prix_max')}€")
    print(f"   Sources: {', '.join(sources)}")
    
    # Créer l'orchestrateur
    orch = Orchestrator()
    rate_limiter = get_rate_limiter()
    
    # Enregistrer les scrapers pour chaque source
    active_sources = []
    scrapers_to_close = []
    
    for source in sources:
        # Vérifier le circuit breaker
        if rate_limiter.is_blocked(source.lower()):
            print(f"   ⏸️ {source}: circuit breaker actif, skip")
            runner_stats.record_source_stats(source, 0, 0, 0, True, 0, 0)
            continue
        
        try:
            index_scraper, detail_scraper, source_enum = create_scrapers_for_source(
                source, search_config
            )
            orch.register_scraper(source_enum, index_scraper, detail_scraper)
            active_sources.append(source_enum)
            scrapers_to_close.append((index_scraper, detail_scraper))
        except Exception as e:
            print(f"   ❌ {source}: erreur création scraper: {e}")
            runner_stats.record_source_stats(source, 0, 0, 0, False, 1, 0)
    
    if not active_sources:
        print("   ⚠️ Aucune source active")
        return PipelineStats()
    
    # Exécuter le pipeline
    try:
        stats = await orch.run_pipeline(
            sources=active_sources,
            detail_threshold=search_config.get("detail_threshold", 30),
            notify_threshold=search_config.get("notify_threshold", 60) if not dry_run else 999,
            max_detail_per_run=runner_config.get("max_detail_per_run", 10),
            max_pages=search_config.get("max_pages", 2),
        )
        
        print(f"   Result: {stats.summary()}")
        
        # Enregistrer stats par source
        for source in sources:
            runner_stats.record_source_stats(
                source,
                scanned=stats.index_scanned // len(sources),  # Approximation
                new=stats.index_new // len(sources),
                duplicates=stats.index_duplicates // len(sources),
                blocked=False,
                errors=0,
                notified=stats.notified // len(sources),
            )
        
        return stats
        
    finally:
        # Fermer les scrapers
        for index_scraper, detail_scraper in scrapers_to_close:
            await index_scraper.close()
            await detail_scraper.close()


async def run_all_searches(dry_run: bool = False) -> tuple[list[PipelineStats], RunnerStats]:
    """Exécute toutes les recherches activées"""
    config = load_searches_config()
    searches = config.get("searches", [])
    runner_config = config.get("runner", {})
    
    enabled_searches = [s for s in searches if s.get("enabled", True)]
    
    print(f"\n{'#'*60}")
    print(f"# VOITURES BOT - Production Run V2 (Multi-Sources)")
    print(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"# Searches: {len(enabled_searches)} enabled")
    print(f"# Dry run: {dry_run}")
    print(f"{'#'*60}")
    
    runner_stats = RunnerStats()
    all_stats: list[PipelineStats] = []
    
    for i, search in enumerate(enabled_searches):
        try:
            stats = await run_search_multi_source(search, runner_config, runner_stats, dry_run)
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
                f"⚠️ 0 listings pendant {runner_stats.consecutive_zero_listings} runs!\n"
                "Possible blocage multi-sources."
            )
    
    # Résumé
    print(f"\n{'='*60}")
    print(f"📊 RUN SUMMARY")
    print(f"   {runner_stats.summary()}")
    print(f"\n📈 Par source:")
    print(runner_stats.source_summary())
    
    total_new = sum(s.index_new for s in all_stats)
    total_detail = sum(s.detail_fetched for s in all_stats)
    total_notif = sum(s.notified for s in all_stats)
    
    print(f"\n   TOTAL: {total_new} new | {total_detail} detail | {total_notif} notified")
    print(f"{'='*60}\n")
    
    # Afficher status circuit breaker
    rate_limiter = get_rate_limiter()
    status = rate_limiter.get_status()
    if status:
        print("🔌 Circuit Breaker Status:")
        for source, info in status.items():
            print(f"   {source}: {info['state']} (failures: {info['failures']})")
    
    return all_stats, runner_stats


def get_jittered_interval(base_sec: int, jitter_sec: int) -> float:
    """Retourne un intervalle avec jitter aléatoire"""
    import random
    return base_sec + random.uniform(-jitter_sec, jitter_sec)


async def run_loop(interval_sec: int = 60, dry_run: bool = False):
    """Exécute en boucle avec intervalle + jitter + backoff."""
    config = load_searches_config()
    defaults = config.get("defaults", {})
    
    base_interval = defaults.get("scan_interval_sec", interval_sec)
    jitter = defaults.get("jitter_sec", 10)
    backoff_mult = defaults.get("backoff_multiplier", 2)
    backoff_max = defaults.get("backoff_max_sec", 300)
    
    print(f"🔄 Starting loop mode (Multi-Sources)")
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
                current_backoff = min(
                    current_backoff * backoff_mult if current_backoff else base_interval,
                    backoff_max
                )
                print(f"⚠️ Possible blocage multi-sources, backoff: {current_backoff}s")
                
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
            sleep_time = get_jittered_interval(base_interval, jitter) + current_backoff
            print(f"💤 Next scan in {sleep_time:.0f}s...")
            
            for _ in range(int(sleep_time)):
                if not running:
                    break
                await asyncio.sleep(1)
    
    print("👋 Loop stopped")


def main():
    parser = argparse.ArgumentParser(description="Voitures Bot - Multi-Source Runner")
    parser.add_argument("--loop", action="store_true", help="Run in loop mode")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="No notifications")
    parser.add_argument("--search", type=str, help="Run specific search only")
    
    args = parser.parse_args()
    
    if args.loop:
        asyncio.run(run_loop(args.interval, args.dry_run))
    else:
        all_stats, runner_stats = asyncio.run(run_all_searches(args.dry_run))
        
        if runner_stats.error_count > 0:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()
