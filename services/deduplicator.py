"""
Deduplication Service - Évite les doublons d'annonces
"""

import hashlib
from typing import List, Set, Optional
from datetime import datetime, timedelta

from models.annonce import Annonce
from models.database import get_db
from utils.logger import get_logger

logger = get_logger(__name__)


class DeduplicationService:
    """Service de déduplication des annonces"""
    
    def __init__(self):
        self.db = get_db()
        self._cache: Set[str] = set()
        self._cache_loaded = False
    
    def _load_cache(self):
        """Charge les URLs connues en cache"""
        if self._cache_loaded:
            return
        
        try:
            annonces = self.db.get_annonces(limit=10000, order_by_score=False)
            self._cache = {a.url for a in annonces}
            self._cache_loaded = True
            logger.debug(f"Cache déduplication chargé: {len(self._cache)} URLs")
        except Exception as e:
            logger.error(f"Erreur chargement cache: {e}")
    
    def est_nouvelle(self, annonce: Annonce) -> bool:
        """Vérifie si une annonce est nouvelle"""
        self._load_cache()
        
        # Vérifier le cache mémoire d'abord
        if annonce.url in self._cache:
            return False
        
        # Vérifier en base
        if self.db.exists(annonce.url):
            self._cache.add(annonce.url)
            return False
        
        return True
    
    def est_nouvelle_url(self, url: str) -> bool:
        """Vérifie si une URL est nouvelle"""
        self._load_cache()
        
        if url in self._cache:
            return False
        
        if self.db.exists(url):
            self._cache.add(url)
            return False
        
        return True
    
    def marquer_vue(self, annonce: Annonce):
        """Marque une annonce comme vue"""
        self._cache.add(annonce.url)
    
    def filtrer_nouvelles(self, annonces: List[Annonce]) -> List[Annonce]:
        """Filtre les annonces pour ne garder que les nouvelles"""
        nouvelles = []
        
        for annonce in annonces:
            if self.est_nouvelle(annonce):
                nouvelles.append(annonce)
                self.marquer_vue(annonce)
        
        if nouvelles:
            logger.info(f"Déduplication: {len(nouvelles)}/{len(annonces)} nouvelles annonces")
        
        return nouvelles
    
    def generer_hash(self, annonce: Annonce) -> str:
        """Génère un hash unique pour une annonce basé sur ses caractéristiques"""
        # Hash basé sur les caractéristiques principales
        data = f"{annonce.marque}|{annonce.modele}|{annonce.prix}|{annonce.kilometrage}|{annonce.departement}"
        return hashlib.md5(data.encode()).hexdigest()
    
    def detecter_doublons_contenu(self, annonces: List[Annonce]) -> List[Annonce]:
        """Détecte les doublons basés sur le contenu (même voiture sur plusieurs sites)"""
        seen_hashes: Set[str] = set()
        uniques = []
        
        for annonce in annonces:
            h = self.generer_hash(annonce)
            if h not in seen_hashes:
                seen_hashes.add(h)
                uniques.append(annonce)
        
        return uniques
    
    def nettoyer_cache(self):
        """Nettoie le cache en mémoire"""
        self._cache.clear()
        self._cache_loaded = False
        logger.debug("Cache déduplication nettoyé")
    
    def get_stats(self) -> dict:
        """Retourne les statistiques du service"""
        return {
            "urls_en_cache": len(self._cache),
            "cache_charge": self._cache_loaded
        }
