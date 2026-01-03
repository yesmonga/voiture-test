"""
Scoring Service - Calcul du score de rentabilité des annonces
"""

from typing import List, Optional, Tuple
from datetime import datetime

from models.annonce import Annonce
from config import (
    VEHICULES_CIBLES, 
    MOTS_CLES_OPPORTUNITE, 
    MOTS_CLES_EXCLUSION,
    SEUILS_ALERTE,
    DEPARTEMENTS_PRIORITAIRES
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ScoringService:
    """Service de scoring des annonces"""
    
    def __init__(self):
        self.vehicules_cibles = VEHICULES_CIBLES
        self.mots_cles_opportunite = MOTS_CLES_OPPORTUNITE
        self.mots_cles_exclusion = MOTS_CLES_EXCLUSION
    
    def calculer_score(self, annonce: Annonce) -> Tuple[int, List[str]]:
        """
        Calcule le score de rentabilité d'une annonce.
        Retourne (score, mots_cles_detectes)
        """
        score = 0
        mots_cles = []
        
        # Identifier le véhicule cible correspondant
        vehicule_id, vehicule_config = self._identifier_vehicule(annonce)
        
        if not vehicule_config:
            return 0, []
        
        # 1. Score Prix (40 points max)
        score += self._score_prix(annonce.prix, vehicule_config)
        
        # 2. Score Kilométrage (30 points max)
        score += self._score_kilometrage(annonce.kilometrage, vehicule_config)
        
        # 3. Score Mots-clés opportunité (20 points max)
        points_mots_cles, mots_cles = self._score_mots_cles(annonce)
        score += points_mots_cles
        
        # 4. Score Fraîcheur (10 points max)
        score += self._score_fraicheur(annonce.date_publication)
        
        # 5. Bonus/Malus
        score += self._score_bonus(annonce, vehicule_config)
        
        # 6. Pénalités (mots-clés d'exclusion)
        if self._contient_exclusion(annonce):
            score = max(0, score - 50)
        
        # Plafonner le score
        score = max(0, min(100, score))
        
        # Mettre à jour l'annonce
        annonce.score_rentabilite = score
        annonce.mots_cles_detectes = mots_cles
        annonce.vehicule_cible_id = vehicule_id
        
        # Calculer la marge estimée
        self._calculer_marge(annonce, vehicule_config)
        
        return score, mots_cles
    
    def _identifier_vehicule(self, annonce: Annonce) -> Tuple[Optional[str], Optional[dict]]:
        """Identifie le véhicule cible correspondant à l'annonce"""
        marque_annonce = (annonce.marque or "").lower()
        modele_annonce = (annonce.modele or "").lower()
        titre = (annonce.titre or "").lower()
        
        for vehicule_id, config in self.vehicules_cibles.items():
            marque_config = config.get("marque", "").lower()
            modeles_config = [m.lower() for m in config.get("modele", [])]
            
            # Vérifier la marque
            if marque_config and marque_config not in marque_annonce and marque_config not in titre:
                continue
            
            # Vérifier le modèle
            modele_match = False
            for modele in modeles_config:
                if modele in modele_annonce or modele in titre:
                    modele_match = True
                    break
            
            if not modele_match and modeles_config:
                continue
            
            # Vérifier les motorisations à inclure
            motorisation_ok = self._verifier_motorisation(annonce, config)
            if not motorisation_ok:
                continue
            
            return vehicule_id, config
        
        return None, None
    
    def _verifier_motorisation(self, annonce: Annonce, config: dict) -> bool:
        """Vérifie si la motorisation correspond aux critères"""
        texte = f"{annonce.titre or ''} {annonce.description or ''} {annonce.motorisation or ''}".lower()
        
        # Vérifier les exclusions d'abord
        for exclu in config.get("motorisation_exclude", []):
            if exclu.lower() in texte:
                return False
        
        # Vérifier les inclusions (au moins une doit matcher)
        inclusions = config.get("motorisation_include", [])
        if not inclusions:
            return True
        
        for inclu in inclusions:
            if inclu.lower() in texte:
                return True
        
        # Si on a des inclusions mais aucune ne matche, 
        # on accepte quand même si on ne peut pas déterminer
        if not annonce.motorisation and not annonce.description:
            return True
        
        return False
    
    def _score_prix(self, prix: Optional[int], config: dict) -> int:
        """Calcule le score basé sur le prix (40 points max)"""
        if not prix:
            return 10  # Score neutre si pas de prix
        
        prix_ideal = config.get("prix_ideal_max", config.get("prix_max", 3000))
        prix_min = config.get("prix_min", 1500)
        prix_max = config.get("prix_max", 4000)
        
        if prix < prix_min:
            return 40  # Très bon prix (possiblement trop beau?)
        elif prix <= prix_ideal * 0.7:
            return 40  # Excellent
        elif prix <= prix_ideal * 0.85:
            return 35
        elif prix <= prix_ideal:
            return 30
        elif prix <= prix_max * 0.9:
            return 20
        elif prix <= prix_max:
            return 10
        else:
            return 0
    
    def _score_kilometrage(self, km: Optional[int], config: dict) -> int:
        """Calcule le score basé sur le kilométrage (30 points max)"""
        if not km:
            return 10  # Score neutre
        
        km_ideal_min = config.get("km_ideal_min", config.get("km_min", 100000))
        km_ideal_max = config.get("km_ideal_max", 160000)
        km_max = config.get("km_max", 200000)
        
        if km < km_ideal_min:
            return 30  # Très bas km
        elif km <= km_ideal_max:
            return 30  # Zone idéale
        elif km <= km_ideal_max * 1.1:
            return 25
        elif km <= km_max * 0.9:
            return 15
        elif km <= km_max:
            return 5
        else:
            return 0
    
    def _score_mots_cles(self, annonce: Annonce) -> Tuple[int, List[str]]:
        """Calcule le score basé sur les mots-clés opportunité (20 points max)"""
        texte = f"{annonce.titre or ''} {annonce.description or ''}".lower()
        mots_trouves = []
        
        for mot in self.mots_cles_opportunite:
            if mot.lower() in texte:
                mots_trouves.append(mot)
        
        # 5 points par mot-clé, max 20 points
        score = min(len(mots_trouves) * 5, 20)
        
        return score, mots_trouves
    
    def _score_fraicheur(self, date_pub: Optional[datetime]) -> int:
        """Calcule le score basé sur la fraîcheur (10 points max)"""
        if not date_pub:
            return 5  # Score neutre
        
        age_minutes = (datetime.now() - date_pub).total_seconds() / 60
        
        if age_minutes < 5:
            return 10
        elif age_minutes < 15:
            return 8
        elif age_minutes < 30:
            return 7
        elif age_minutes < 60:
            return 5
        elif age_minutes < 120:
            return 3
        else:
            return 0
    
    def _score_bonus(self, annonce: Annonce, config: dict) -> int:
        """Calcule les bonus/malus additionnels"""
        bonus = 0
        texte = f"{annonce.titre or ''} {annonce.description or ''}".lower()
        
        # Bonus département prioritaire
        if annonce.departement in DEPARTEMENTS_PRIORITAIRES:
            bonus += 5
        
        # Bonus Stepway au prix Sandero
        if config.get("bonus_stepway"):
            if "stepway" in texte:
                prix_max_sandero = config.get("prix_ideal_max", 3200)
                if annonce.prix and annonce.prix <= prix_max_sandero:
                    bonus += 10
        
        # Bonus Phase 2 au prix Phase 1 (Twingo)
        if "twingo" in texte:
            if "phase 2" in texte or annonce.annee and annonce.annee >= 2012:
                bonus += 5
        
        # Bonus vendeur particulier
        if annonce.type_vendeur == "particulier":
            bonus += 3
        
        # Malus si peu d'infos
        if not annonce.description:
            bonus -= 5
        if not annonce.images_urls:
            bonus -= 5
        
        return bonus
    
    def _contient_exclusion(self, annonce: Annonce) -> bool:
        """Vérifie si l'annonce contient des mots-clés d'exclusion"""
        texte = f"{annonce.titre or ''} {annonce.description or ''}".lower()
        
        for mot in self.mots_cles_exclusion:
            if mot.lower() in texte:
                return True
        
        return False
    
    def _calculer_marge(self, annonce: Annonce, config: dict):
        """Calcule la marge potentielle estimée"""
        if not annonce.prix:
            return
        
        prix_revente = config.get("prix_revente", {})
        revente_min = prix_revente.get("min", annonce.prix + 500)
        revente_max = prix_revente.get("max", annonce.prix + 1000)
        
        # Ajuster selon l'état (mots-clés de problèmes = coûts de réparation)
        cout_reparation_estime = len(annonce.mots_cles_detectes) * 100
        
        annonce.marge_estimee_min = max(0, revente_min - annonce.prix - cout_reparation_estime)
        annonce.marge_estimee_max = max(0, revente_max - annonce.prix - cout_reparation_estime // 2)
    
    def filtrer_par_score(self, annonces: List[Annonce], score_min: int = 40) -> List[Annonce]:
        """Filtre les annonces par score minimum"""
        return [a for a in annonces if a.score_rentabilite >= score_min]
    
    def trier_par_score(self, annonces: List[Annonce]) -> List[Annonce]:
        """Trie les annonces par score décroissant"""
        return sorted(annonces, key=lambda a: a.score_rentabilite, reverse=True)
    
    def get_niveau_alerte(self, score: int) -> str:
        """Retourne le niveau d'alerte pour un score donné"""
        if score >= SEUILS_ALERTE["urgent"]:
            return "urgent"
        elif score >= SEUILS_ALERTE["interessant"]:
            return "interessant"
        elif score >= SEUILS_ALERTE["surveiller"]:
            return "surveiller"
        return "archive"
