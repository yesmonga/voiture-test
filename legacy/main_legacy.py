#!/usr/bin/env python3
"""
Bot de Détection de Véhicules d'Occasion
=========================================
Surveille les annonces sur LeBoncoin, LaCentrale, ParuVendu et AutoScout24
pour trouver des opportunités d'achat rentables.

Usage:
    python main.py              # Lance le bot en mode continu
    python main.py --once       # Exécute un seul cycle de scraping
    python main.py --test       # Mode test (notifications désactivées)
    python main.py --stats      # Affiche les statistiques
"""

import asyncio
import argparse
import signal
import sys
from datetime import datetime
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import SCRAPING_INTERVALS, SEUILS_ALERTE, DEBUG
from models.database import get_db, Database
from models.annonce import Annonce
from scrapers import LaCentraleScraper, ParuVenduScraper, AutoScout24Scraper
from scrapers.leboncoin_playwright import LeBoncoinPlaywrightScraper
from services.scorer import ScoringService
from services.notifier import NotificationService
from services.deduplicator import DeduplicationService
from services.analyzer import AnalyzerService
from utils.logger import setup_logger, get_logger

logger = get_logger(__name__)
console = Console()


class VoituresBot:
    """Bot principal de surveillance des annonces"""
    
    def __init__(self, test_mode: bool = False):
        self.test_mode = test_mode
        self.db = get_db()
        self.scorer = ScoringService()
        self.notifier = NotificationService()
        self.deduplicator = DeduplicationService()
        self.analyzer = AnalyzerService()
        
        self.scrapers = {
            "leboncoin": LeBoncoinPlaywrightScraper(),
            "lacentrale": LaCentraleScraper(),
            "paruvendu": ParuVenduScraper(),
            "autoscout24": AutoScout24Scraper(),
        }
        
        self.scheduler = None
        self.running = False
        self.stats = {
            "cycles": 0,
            "annonces_trouvees": 0,
            "annonces_notifiees": 0,
            "derniere_execution": None,
        }
    
    async def scrape_source(self, source_name: str) -> List[Annonce]:
        """Scrape une source spécifique"""
        scraper = self.scrapers.get(source_name)
        if not scraper:
            logger.error(f"Scraper inconnu: {source_name}")
            return []
        
        try:
            logger.info(f"🔍 Scraping {source_name}...")
            annonces = await scraper.scrape_all()
            
            # Filtrer les nouvelles annonces
            nouvelles = self.deduplicator.filtrer_nouvelles(annonces)
            
            # Scorer les annonces
            for annonce in nouvelles:
                self.scorer.calculer_score(annonce)
                self.db.save_annonce(annonce)
            
            logger.info(f"✅ {source_name}: {len(nouvelles)} nouvelles annonces")
            return nouvelles
            
        except Exception as e:
            logger.error(f"❌ Erreur scraping {source_name}: {e}")
            return []
    
    async def process_annonces(self, annonces: List[Annonce]):
        """Traite les annonces (scoring, notification)"""
        if not annonces:
            return
        
        # Trier par score
        annonces_triees = self.scorer.trier_par_score(annonces)
        
        for annonce in annonces_triees:
            # Analyser
            analyse = self.analyzer.analyser(annonce)
            
            # Log
            niveau = annonce.niveau_alerte
            if niveau in ["urgent", "interessant"]:
                self._afficher_annonce(annonce, analyse)
            
            # Notifier si score suffisant et pas en mode test
            if not self.test_mode and annonce.score_rentabilite >= SEUILS_ALERTE["surveiller"]:
                if not annonce.notifie:
                    success = await self.notifier.notifier(annonce)
                    if success:
                        self.db.mark_notified(annonce.id)
                        self.stats["annonces_notifiees"] += 1
    
    def _afficher_annonce(self, annonce: Annonce, analyse: dict = None):
        """Affiche une annonce dans la console"""
        couleur = {
            "urgent": "red",
            "interessant": "yellow",
            "surveiller": "blue",
            "archive": "white"
        }.get(annonce.niveau_alerte, "white")
        
        table = Table(show_header=False, box=None)
        table.add_column("Label", style="bold")
        table.add_column("Value")
        
        table.add_row("Véhicule", f"{annonce.marque} {annonce.modele}")
        table.add_row("Prix", f"{annonce.prix:,}€" if annonce.prix else "N/A")
        table.add_row("Km", f"{annonce.kilometrage:,} km" if annonce.kilometrage else "N/A")
        table.add_row("Année", str(annonce.annee) if annonce.annee else "N/A")
        table.add_row("Lieu", f"{annonce.ville} ({annonce.departement})")
        table.add_row("Score", f"{annonce.score_rentabilite}/100")
        
        if annonce.marge_estimee_min and annonce.marge_estimee_max:
            table.add_row("Marge", f"{annonce.marge_estimee_min}€ - {annonce.marge_estimee_max}€")
        
        if annonce.mots_cles_detectes:
            table.add_row("Mots-clés", ", ".join(annonce.mots_cles_detectes[:3]))
        
        table.add_row("URL", annonce.url)
        
        console.print(Panel(
            table,
            title=f"{annonce.emoji_alerte} {annonce.niveau_alerte.upper()}",
            border_style=couleur
        ))
    
    async def run_cycle(self):
        """Exécute un cycle complet de scraping"""
        logger.info("=" * 50)
        logger.info(f"🚀 Début du cycle #{self.stats['cycles'] + 1}")
        
        toutes_annonces = []
        
        # Scraper chaque source
        for source_name in self.scrapers.keys():
            annonces = await self.scrape_source(source_name)
            toutes_annonces.extend(annonces)
            
            # Pause entre les sources
            await asyncio.sleep(5)
        
        # Traiter les annonces
        await self.process_annonces(toutes_annonces)
        
        # Mettre à jour les stats
        self.stats["cycles"] += 1
        self.stats["annonces_trouvees"] += len(toutes_annonces)
        self.stats["derniere_execution"] = datetime.now()
        
        logger.info(f"✅ Cycle terminé: {len(toutes_annonces)} nouvelles annonces")
        logger.info("=" * 50)
    
    async def start(self):
        """Démarre le bot en mode continu"""
        self.running = True
        
        console.print(Panel.fit(
            "[bold green]🚗 Bot Voitures Démarré[/bold green]\n"
            f"Mode: {'TEST' if self.test_mode else 'PRODUCTION'}\n"
            f"Sources: {', '.join(self.scrapers.keys())}",
            title="Bot Voitures"
        ))
        
        # Afficher le statut des notifications
        notif_status = self.notifier.get_status()
        console.print(f"📱 Notifications: {notif_status}")
        
        # Créer le scheduler
        self.scheduler = AsyncIOScheduler()
        
        # Ajouter les jobs pour chaque source
        for source_name, interval in SCRAPING_INTERVALS.items():
            if source_name in self.scrapers:
                self.scheduler.add_job(
                    self.scrape_source,
                    IntervalTrigger(seconds=interval),
                    args=[source_name],
                    id=f"scrape_{source_name}",
                    name=f"Scraping {source_name}",
                    max_instances=1,
                    coalesce=True
                )
                logger.info(f"📅 Job planifié: {source_name} toutes les {interval}s")
        
        # Job de traitement des annonces non notifiées
        self.scheduler.add_job(
            self._process_pending,
            IntervalTrigger(minutes=5),
            id="process_pending",
            name="Traitement annonces en attente"
        )
        
        # Démarrer le scheduler
        self.scheduler.start()
        
        # Exécuter un premier cycle immédiatement
        await self.run_cycle()
        
        # Boucle principale
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def _process_pending(self):
        """Traite les annonces non notifiées"""
        try:
            annonces = self.db.get_non_notifiees(score_min=SEUILS_ALERTE["surveiller"])
            if annonces:
                logger.info(f"📬 Traitement de {len(annonces)} annonces en attente")
                await self.process_annonces(annonces)
        except Exception as e:
            logger.error(f"Erreur traitement pending: {e}")
    
    async def stop(self):
        """Arrête le bot proprement"""
        self.running = False
        
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        
        console.print("[bold yellow]⏹️ Bot arrêté[/bold yellow]")
    
    def afficher_stats(self):
        """Affiche les statistiques"""
        db_stats = self.db.get_stats()
        
        table = Table(title="📊 Statistiques du Bot")
        table.add_column("Métrique", style="cyan")
        table.add_column("Valeur", style="green")
        
        table.add_row("Cycles exécutés", str(self.stats["cycles"]))
        table.add_row("Annonces trouvées", str(self.stats["annonces_trouvees"]))
        table.add_row("Notifications envoyées", str(self.stats["annonces_notifiees"]))
        table.add_row("Dernière exécution", 
                     self.stats["derniere_execution"].strftime("%H:%M:%S") 
                     if self.stats["derniere_execution"] else "N/A")
        
        table.add_section()
        table.add_row("Total en base", str(db_stats["total"]))
        
        for source, count in db_stats["par_source"].items():
            table.add_row(f"  - {source}", str(count))
        
        table.add_section()
        table.add_row("🔴 Urgent (≥80)", str(db_stats["par_score"]["urgent"]))
        table.add_row("🟠 Intéressant (≥60)", str(db_stats["par_score"]["interessant"]))
        table.add_row("🟡 À surveiller (≥40)", str(db_stats["par_score"]["surveiller"]))
        table.add_row("⚪ Archive (<40)", str(db_stats["par_score"]["archive"]))
        
        console.print(table)


async def main():
    """Point d'entrée principal"""
    parser = argparse.ArgumentParser(description="Bot de Détection de Véhicules d'Occasion")
    parser.add_argument("--once", action="store_true", help="Exécuter un seul cycle")
    parser.add_argument("--test", action="store_true", help="Mode test (pas de notifications)")
    parser.add_argument("--stats", action="store_true", help="Afficher les statistiques")
    parser.add_argument("--source", type=str, help="Scraper une source spécifique")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logger()
    
    # Créer le bot
    bot = VoituresBot(test_mode=args.test or DEBUG)
    
    # Gestion des signaux
    def signal_handler(sig, frame):
        logger.info("Signal d'arrêt reçu...")
        asyncio.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if args.stats:
            bot.afficher_stats()
        elif args.source:
            annonces = await bot.scrape_source(args.source)
            await bot.process_annonces(annonces)
            bot.afficher_stats()
        elif args.once:
            await bot.run_cycle()
            bot.afficher_stats()
        else:
            await bot.start()
    except KeyboardInterrupt:
        await bot.stop()
    except Exception as e:
        logger.error(f"Erreur fatale: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
