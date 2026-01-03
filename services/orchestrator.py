"""
Orchestrator - Pipeline 2 passes temps réel
1. Index scan (rapide) → scoring light
2. Detail fetch (sélectif) → scoring final + notif

Delta scan : ne traite que les nouvelles annonces (fingerprint/url)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol
from enum import Enum

from models.annonce_v2 import Annonce, ScoreBreakdown
from models.enums import Source, AlertLevel, AnnonceStatus
from services.scoring_v2 import get_scoring_service_v3, ScoringServiceV3
from services.normalize import get_normalize_service, NormalizeService
from services.keywords import normalize_text
from db.repo import get_repo, AnnonceRepository
from config.settings import get_settings


class ScanPhase(Enum):
    INDEX = "index"
    DETAIL = "detail"


@dataclass
class IndexResult:
    """Résultat d'un scan index (données légères)"""
    url: str
    source: Source
    titre: str = ""
    prix: Optional[int] = None
    kilometrage: Optional[int] = None
    annee: Optional[int] = None
    ville: str = ""
    departement: str = ""
    published_at: Optional[datetime] = None
    thumbnail_url: str = ""
    source_listing_id: str = ""
    
    # Champs véhicule (optionnels, enrichis par scraper)
    marque: str = ""
    modele: str = ""
    version: str = ""
    carburant: str = ""
    
    # Scoring light
    score_light: int = 0
    priority: int = 0  # Pour la queue (plus haut = plus prioritaire)


@dataclass
class DetailResult:
    """Résultat d'un fetch détail (données complètes)"""
    description: str = ""
    images_urls: list[str] = field(default_factory=list)
    seller_type: str = ""
    seller_name: str = ""
    seller_phone: str = ""
    carburant: str = ""
    boite: str = ""
    puissance_ch: Optional[int] = None
    version: str = ""
    motorisation: str = ""
    ct_info: str = ""  # Info contrôle technique


class IndexScraper(Protocol):
    """Interface pour un scraper d'index"""
    async def scan_index(self, **kwargs) -> list[IndexResult]: ...


class DetailScraper(Protocol):
    """Interface pour un scraper de détails"""
    async def fetch_detail(self, url: str) -> Optional[DetailResult]: ...


@dataclass
class PipelineStats:
    """Statistiques d'exécution du pipeline"""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    
    # Index phase
    index_scanned: int = 0
    index_new: int = 0
    index_duplicates: int = 0
    index_errors: int = 0
    
    # Detail phase
    detail_fetched: int = 0
    detail_errors: int = 0
    
    # Scoring
    score_above_threshold: int = 0
    urgent_count: int = 0
    interessant_count: int = 0
    
    # Notifications
    notified: int = 0
    notif_errors: int = 0
    
    @property
    def duration_seconds(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()
    
    def summary(self) -> str:
        return (
            f"Index: {self.index_scanned} scannés, {self.index_new} nouveaux, "
            f"{self.index_duplicates} doublons | "
            f"Detail: {self.detail_fetched} récupérés | "
            f"Score: {self.urgent_count} urgents, {self.interessant_count} intéressants | "
            f"Notifs: {self.notified} | "
            f"Durée: {self.duration_seconds:.1f}s"
        )


class Orchestrator:
    """
    Orchestrateur du pipeline de scraping temps réel.
    
    Flow:
    1. Index scan → liste d'IndexResult
    2. Filtrage doublons (fingerprint/url dans cache + DB)
    3. Scoring light sur les nouveaux
    4. Queue prioritaire (score_light + fraîcheur)
    5. Detail fetch pour score >= threshold
    6. Scoring final
    7. Persist + Notify
    """
    
    def __init__(
        self,
        repo: Optional[AnnonceRepository] = None,
        scorer: Optional[ScoringServiceV3] = None,
        normalizer: Optional[NormalizeService] = None
    ):
        self.repo = repo or get_repo()
        self.scorer = scorer or get_scoring_service_v3()
        self.normalizer = normalizer or get_normalize_service()
        self.settings = get_settings()
        
        # Cache en mémoire pour éviter DB lookups répétés
        self._seen_urls: set[str] = set()
        self._seen_source_listings: set[tuple[str, str]] = set()  # (source, source_listing_id)
        
        # Scrapers enregistrés
        self._index_scrapers: dict[Source, IndexScraper] = {}
        self._detail_scrapers: dict[Source, DetailScraper] = {}
        
        # Callbacks
        self._on_new_annonce: Optional[Callable[[Annonce], None]] = None
        self._on_urgent: Optional[Callable[[Annonce], None]] = None
        
        # Concurrence pour detail fetch
        self._detail_semaphore = asyncio.Semaphore(5)  # Max 5 fetches en parallèle
    
    def register_scraper(
        self,
        source: Source,
        index_scraper: IndexScraper,
        detail_scraper: Optional[DetailScraper] = None
    ):
        """Enregistre un scraper pour une source"""
        self._index_scrapers[source] = index_scraper
        if detail_scraper:
            self._detail_scrapers[source] = detail_scraper
    
    def on_new_annonce(self, callback: Callable[[Annonce], None]):
        """Callback appelé pour chaque nouvelle annonce"""
        self._on_new_annonce = callback
    
    def on_urgent(self, callback: Callable[[Annonce], None]):
        """Callback appelé pour les annonces urgentes"""
        self._on_urgent = callback
    
    async def run_pipeline(
        self,
        sources: Optional[list[Source]] = None,
        detail_threshold: int = 50,
        notify_threshold: int = 60,
        max_detail_per_run: int = 20,
        **scraper_kwargs
    ) -> PipelineStats:
        """
        Exécute le pipeline complet.
        
        Args:
            sources: Sources à scanner (toutes si None)
            detail_threshold: Score minimum pour fetch détail
            notify_threshold: Score minimum pour notification
            max_detail_per_run: Limite de fetches détail par run
            **scraper_kwargs: Arguments passés aux scrapers
        
        Returns:
            Statistiques d'exécution
        """
        stats = PipelineStats()
        
        # Sources à scanner
        if sources is None:
            sources = list(self._index_scrapers.keys())
        
        # Phase 1: Index scan
        all_index_results: list[IndexResult] = []
        
        for source in sources:
            if source not in self._index_scrapers:
                continue
            
            try:
                results = await self._index_scrapers[source].scan_index(**scraper_kwargs)
                for r in results:
                    r.source = source
                all_index_results.extend(results)
                stats.index_scanned += len(results)
            except Exception as e:
                print(f"❌ Index scan error {source.value}: {e}")
                stats.index_errors += 1
        
        # Phase 2: Filtrage doublons
        new_results = []
        for result in all_index_results:
            if self._is_duplicate(result):
                stats.index_duplicates += 1
                continue
            new_results.append(result)
            stats.index_new += 1
        
        # Phase 3: Scoring light + priorité
        scored_results = self._score_light_batch(new_results)
        
        # Trier par priorité (score + fraîcheur)
        scored_results.sort(key=lambda r: r.priority, reverse=True)
        
        # Phase 4: Sélection pour détail
        to_detail = [r for r in scored_results if r.score_light >= detail_threshold]
        to_detail = to_detail[:max_detail_per_run]
        
        stats.score_above_threshold = len(to_detail)
        
        # Phase 5: Detail fetch + scoring final (avec concurrence)
        async def process_one(index_result: IndexResult) -> Optional[Annonce]:
            async with self._detail_semaphore:
                return await self._process_with_detail(index_result, notify_threshold)
        
        # Lancer en parallèle avec semaphore
        tasks = [process_one(r) for r in to_detail]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"❌ Detail error {to_detail[i].url}: {result}")
                stats.detail_errors += 1
            elif result is not None:
                annonce = result
                stats.detail_fetched += 1
                
                # Stats par niveau
                if annonce.alert_level == AlertLevel.URGENT:
                    stats.urgent_count += 1
                elif annonce.alert_level == AlertLevel.INTERESSANT:
                    stats.interessant_count += 1
                
                if annonce.notified:
                    stats.notified += 1
                
                # Callback
                if self._on_new_annonce:
                    self._on_new_annonce(annonce)
                if annonce.alert_level == AlertLevel.URGENT and self._on_urgent:
                    self._on_urgent(annonce)
        
        # Log scan history
        self._log_scan_history(sources, stats)
        
        stats.finished_at = datetime.now(timezone.utc)
        return stats
    
    def _is_duplicate(self, result: IndexResult) -> bool:
        """
        Vérifie si une annonce est un doublon.
        Priorité: source_listing_id > url_canonique
        """
        from models.annonce_v2 import canonicalize_url
        
        # 1. Check par source_listing_id (le plus fiable)
        if result.source_listing_id:
            key = (result.source.value, result.source_listing_id)
            if key in self._seen_source_listings:
                return True
            
            # Check DB
            existing = self.repo.get_by_source_listing(result.source, result.source_listing_id)
            if existing:
                self._seen_source_listings.add(key)
                return True
            
            self._seen_source_listings.add(key)
        
        # 2. Fallback: check par URL
        url_canon = canonicalize_url(result.url)
        
        if url_canon in self._seen_urls:
            return True
        
        if self.repo.exists(url=url_canon):
            self._seen_urls.add(url_canon)
            return True
        
        self._seen_urls.add(url_canon)
        return False
    
    def _score_light_batch(self, results: list[IndexResult]) -> list[IndexResult]:
        """
        Scoring léger basé sur les données d'index uniquement.
        Calcule aussi la priorité pour la queue.
        """
        for result in results:
            score = 0
            priority = 0
            
            # Score prix (approximatif sans config véhicule)
            if result.prix:
                if result.prix < 2000:
                    score += 25
                    priority += 20
                elif result.prix < 3000:
                    score += 20
                    priority += 10
                elif result.prix < 4000:
                    score += 10
            
            # Score km
            if result.kilometrage:
                if 80000 <= result.kilometrage <= 150000:
                    score += 20
                elif result.kilometrage < 80000:
                    score += 15
                elif result.kilometrage <= 200000:
                    score += 10
            
            # Score fraîcheur (boost priorité)
            if result.published_at:
                age_hours = (datetime.now(timezone.utc) - result.published_at).total_seconds() / 3600
                if age_hours < 1:
                    score += 15
                    priority += 30  # Très prioritaire
                elif age_hours < 6:
                    score += 10
                    priority += 20
                elif age_hours < 24:
                    score += 5
                    priority += 10
            
            # Détection mots-clés dans titre (normalisé - sans accents)
            titre_normalized = normalize_text(result.titre or "")
            if any(kw in titre_normalized for kw in ["urgent", "vite", "depart", "demenagement"]):
                score += 10
                priority += 15
            if any(kw in titre_normalized for kw in ["negociable", "a debattre", "nego"]):
                score += 5
            if any(kw in titre_normalized for kw in ["ct ok", "ct vierge", "controle technique ok"]):
                score += 8
            
            # Pénalité mots risque dans titre (normalisé)
            if any(kw in titre_normalized for kw in ["hs", "panne", "accident", "epave", "pour pieces"]):
                score -= 20
            
            result.score_light = max(0, score)
            result.priority = priority + score
        
        return results
    
    async def _process_with_detail(
        self, 
        index_result: IndexResult,
        notify_threshold: int = 60
    ) -> Optional[Annonce]:
        """
        Fetch le détail et crée l'annonce complète.
        Utilise should_notify pour des notifications intelligentes.
        """
        from services.notifier.discord import should_notify, send_update_notification
        
        source = index_result.source
        
        # Chercher une annonce existante (pour near-duplicate / update)
        existing = None
        if index_result.source_listing_id:
            existing = self.repo.get_by_source_listing(source, index_result.source_listing_id)
        
        # Créer l'annonce de base depuis l'index
        annonce = self._index_to_annonce(index_result)
        
        # Check near-duplicate
        is_near_dup, near_dup_existing = self.repo.is_near_duplicate(annonce)
        if is_near_dup and near_dup_existing and not existing:
            # Near-duplicate trouvé - on peut merger ou ignorer
            existing = near_dup_existing
        
        # Fetch détail si scraper disponible
        if source in self._detail_scrapers:
            try:
                detail = await self._detail_scrapers[source].fetch_detail(index_result.url)
                if detail:
                    self._merge_detail(annonce, detail)
            except Exception as e:
                print(f"⚠️ Detail fetch failed: {e}")
        
        # Scoring final
        self.scorer.calculate_score(annonce)
        
        # Décider si on notifie (intelligent)
        do_notify, reason = should_notify(annonce, existing, min_score=notify_threshold)
        
        if do_notify:
            if reason in ("price_dropped", "score_increased") and existing:
                # Notification de mise à jour
                success = await send_update_notification(
                    annonce,
                    old_prix=existing.prix,
                    old_score=existing.score_total
                )
            else:
                # Nouvelle notification
                success = await self._notify_annonce(annonce)
            
            if success:
                annonce.mark_notified(["discord"])
        
        # Persist (upsert sur fingerprint)
        self.repo.save(annonce)
        
        return annonce
    
    def _index_to_annonce(self, result: IndexResult) -> Annonce:
        """Convertit un IndexResult en Annonce"""
        # Utiliser marque/modele du scraper si disponible, sinon parser le titre
        marque = result.marque
        modele = result.modele
        version = result.version
        
        if not marque or not modele:
            parsed_marque, parsed_modele, parsed_version = self.normalizer.parse_title(result.titre)
            marque = marque or parsed_marque
            modele = modele or parsed_modele
            version = version or parsed_version
        
        return Annonce(
            source=result.source,
            source_listing_id=result.source_listing_id,
            url=result.url,
            titre=result.titre,
            marque=marque,
            modele=modele,
            version=version,
            prix=result.prix,
            kilometrage=result.kilometrage,
            annee=result.annee,
            ville=result.ville,
            departement=result.departement or self.normalizer.parse_departement(result.ville),
            published_at=result.published_at,
            images_urls=[result.thumbnail_url] if result.thumbnail_url else [],
        )
    
    def _merge_detail(self, annonce: Annonce, detail: DetailResult):
        """Fusionne les données de détail dans l'annonce"""
        annonce.description = detail.description
        
        if detail.images_urls:
            annonce.images_urls = detail.images_urls
        
        if detail.seller_type:
            annonce.seller_type = self.normalizer.parse_seller_type(detail.seller_type)
        annonce.seller_name = detail.seller_name
        annonce.seller_phone = detail.seller_phone
        
        if detail.carburant:
            annonce.carburant = self.normalizer.parse_carburant(detail.carburant)
        if detail.boite:
            annonce.boite = self.normalizer.parse_boite(detail.boite)
        
        annonce.puissance_ch = detail.puissance_ch
        
        if detail.version and not annonce.version:
            annonce.version = detail.version
        if detail.motorisation:
            annonce.motorisation = detail.motorisation
    
    async def _notify_annonce(self, annonce: Annonce) -> bool:
        """Envoie la notification pour une annonce"""
        if annonce.notified:
            return False
        
        try:
            from services.notifier.discord import send_discord_notification
            success = await send_discord_notification(annonce)
            if success:
                self.repo.mark_notified(annonce.id, ["discord"])
            return success
        except Exception as e:
            print(f"❌ Notification error: {e}")
            return False
    
    def _log_scan_history(self, sources: list[Source], stats: PipelineStats):
        """Log l'historique du scan pour observabilité"""
        try:
            for source in sources:
                self.repo.log_scan(
                    source=source.value,
                    index_count=stats.index_scanned,
                    new_count=stats.index_new,
                    notified_count=stats.notified,
                    error_count=stats.index_errors + stats.detail_errors
                )
        except Exception as e:
            print(f"⚠️ Failed to log scan history: {e}")
    
    def clear_cache(self):
        """Vide le cache en mémoire"""
        self._seen_urls.clear()
        self._seen_source_listings.clear()
    
    def preload_cache(self, hours: int = 24):
        """
        Précharge le cache avec les annonces récentes.
        Évite de re-traiter les annonces déjà vues.
        """
        from datetime import timedelta
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Charger les URLs des dernières X heures
        annonces = self.repo.get_all(limit=5000, order_by="created_at DESC")
        
        for a in annonces:
            if a.created_at and a.created_at >= cutoff:
                self._seen_urls.add(a.url_canonique)
                if a.source_listing_id:
                    self._seen_source_listings.add((a.source.value, a.source_listing_id))


# Instance globale
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Retourne l'instance de l'orchestrateur"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
