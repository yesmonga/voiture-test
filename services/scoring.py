"""
Scoring Service V2 - Calcul de score explicable
- Poids configurables depuis YAML
- Breakdown stocké pour transparence
- Estimation marge basée sur coûts réels
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from models.annonce_v2 import Annonce, ScoreBreakdown
from models.enums import AlertLevel, SellerType, AnnonceStatus
from config.settings import CONFIG_DIR


def load_yaml(filename: str) -> dict[str, Any]:
    """Charge un fichier YAML de config"""
    path = CONFIG_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class ScoringService:
    """
    Service de scoring V2 - Production grade
    
    Calcule un score 0-100 avec breakdown explicable:
    - Prix vs marché/config (40 pts)
    - Kilométrage (30 pts)
    - Mots-clés opportunité (15 pts)
    - Fraîcheur (10 pts)
    - Bonus divers (5 pts)
    - Pénalités risques (soustractif)
    """
    
    def __init__(self):
        # Charger les configs YAML
        self.vehicles_config = load_yaml("vehicles.yaml")
        self.keywords_config = load_yaml("keywords.yaml")
        
        # Poids du scoring
        self.weights = self.vehicles_config.get("scoring_weights", {
            "prix": 40,
            "km": 30,
            "keywords": 15,
            "freshness": 10,
            "bonus": 5
        })
        
        # Véhicules cibles
        self.vehicles = self.vehicles_config.get("vehicles", {})
        
        # Départements prioritaires
        self.dept_priority = self.vehicles_config.get("departements_prioritaires", {})
        
        # Mots-clés
        self.keywords_opportunite = self.keywords_config.get("opportunite", {})
        self.keywords_risque = self.keywords_config.get("risque", {})
        self.exclusions = self.keywords_config.get("exclusions", {})
    
    def calculate_score(self, annonce: Annonce) -> ScoreBreakdown:
        """
        Calcule le score complet avec breakdown.
        Retourne un ScoreBreakdown détaillé.
        """
        breakdown = ScoreBreakdown()
        
        # 1. Identifier le véhicule cible
        vehicle_id, vehicle_config = self._identify_vehicle(annonce)
        if not vehicle_config:
            breakdown.total = 0
            breakdown.prix_detail = "Véhicule non ciblé"
            return breakdown
        
        annonce.vehicule_cible_id = vehicle_id
        
        # 2. Vérifier exclusions absolues
        excluded, exclude_reason = self._check_exclusions(annonce)
        if excluded:
            breakdown.total = 0
            breakdown.risk_detail = f"EXCLU: {exclude_reason}"
            annonce.status = AnnonceStatus.EXCLUE
            annonce.ignore_reason = exclude_reason
            return breakdown
        
        # 3. Calculer chaque composante
        breakdown.prix_score, breakdown.prix_detail = self._score_prix(
            annonce, vehicle_config
        )
        
        breakdown.km_score, breakdown.km_detail = self._score_km(
            annonce, vehicle_config
        )
        
        breakdown.freshness_score, breakdown.freshness_detail = self._score_freshness(
            annonce
        )
        
        breakdown.keywords_score, breakdown.keywords_detail = self._score_keywords(
            annonce
        )
        
        breakdown.bonus_score, breakdown.bonus_detail = self._score_bonus(
            annonce, vehicle_config
        )
        
        breakdown.risk_penalty, breakdown.risk_detail = self._score_risks(
            annonce
        )
        
        # 4. Calculer le total
        raw_score = (
            breakdown.prix_score +
            breakdown.km_score +
            breakdown.freshness_score +
            breakdown.keywords_score +
            breakdown.bonus_score +
            breakdown.risk_penalty  # Négatif
        )
        
        breakdown.total = max(0, min(100, raw_score))
        
        # 5. Estimer la marge
        breakdown.margin_min, breakdown.margin_max, breakdown.repair_cost_estimate = (
            self._estimate_margin(annonce, vehicle_config)
        )
        
        # 6. Mettre à jour l'annonce
        annonce.update_score(breakdown.total, breakdown)
        
        return breakdown
    
    def _identify_vehicle(
        self, 
        annonce: Annonce
    ) -> tuple[str, Optional[dict[str, Any]]]:
        """
        Identifie le véhicule cible correspondant à l'annonce.
        Utilise des regex avec frontières de mots pour éviter les faux positifs.
        """
        if not annonce.marque or not annonce.modele:
            return "", None
        
        annonce_marque = annonce.marque.lower().strip()
        annonce_modele = annonce.modele.lower().strip()
        annonce_titre = (annonce.titre or "").lower()
        annonce_version = (annonce.version or "").lower()
        
        for vehicle_id, config in self.vehicles.items():
            # Vérifier la marque
            config_marque = config.get("marque", "").lower()
            if config_marque not in annonce_marque and annonce_marque not in config_marque:
                continue
            
            # Vérifier le modèle avec patterns regex
            modele_patterns = config.get("modele_patterns", [])
            modele_match = False
            
            for pattern in modele_patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                    if (regex.search(annonce_modele) or 
                        regex.search(annonce_titre) or
                        regex.search(annonce_version)):
                        modele_match = True
                        break
                except re.error:
                    # Pattern invalide, essayer matching simple
                    pattern_clean = pattern.replace("^", "").replace("$", "").replace("\\s", " ")
                    if pattern_clean.lower() in annonce_modele:
                        modele_match = True
                        break
            
            if not modele_match:
                continue
            
            # Vérifier le carburant si spécifié
            config_carburant = config.get("carburant")
            if config_carburant:
                annonce_carburant = str(annonce.carburant.value).lower()
                if config_carburant.lower() not in annonce_carburant:
                    # Vérifier aussi dans le titre/version
                    text_to_check = f"{annonce_titre} {annonce_version}"
                    carburant_ok = False
                    
                    if config_carburant == "diesel":
                        if any(p in text_to_check for p in ["hdi", "dci", "tdi", "diesel", "d-4d"]):
                            carburant_ok = True
                    elif config_carburant == "essence":
                        if any(p in text_to_check for p in ["vti", "tce", "essence", "1.2", "1.4"]):
                            carburant_ok = True
                    
                    if not carburant_ok and annonce_carburant != "unknown":
                        continue
            
            # Vérifier les exclusions du véhicule
            exclusions = config.get("exclusions", [])
            excluded = False
            for excl in exclusions:
                if excl.lower() in annonce_titre or excl.lower() in annonce_version:
                    excluded = True
                    break
            
            if excluded:
                continue
            
            return vehicle_id, config
        
        return "", None
    
    def _check_exclusions(self, annonce: Annonce) -> tuple[bool, str]:
        """Vérifie les exclusions absolues (score = 0)"""
        text_to_check = " ".join([
            annonce.titre or "",
            annonce.description or "",
            annonce.version or ""
        ]).lower()
        
        exclusion_patterns = self.exclusions.get("patterns", [])
        
        for pattern in exclusion_patterns:
            if pattern.lower() in text_to_check:
                return True, f"Mot-clé exclu: {pattern}"
        
        return False, ""
    
    def _score_prix(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, str]:
        """
        Score prix (max 40 pts).
        Basé sur écart avec prix marché estimé ou config.
        """
        max_pts = self.weights.get("prix", 40)
        
        if annonce.prix is None:
            return 0, "Prix non renseigné"
        
        criteres = vehicle_config.get("criteres", {})
        estimation = vehicle_config.get("estimation", {})
        
        prix_min = criteres.get("prix_min", 1000)
        prix_max = criteres.get("prix_max", 5000)
        prix_marche = estimation.get("prix_marche_median") or annonce.prix_marche_estime
        
        # Hors fourchette = score réduit
        if annonce.prix < prix_min:
            return int(max_pts * 0.3), f"Prix très bas ({annonce.prix}€ < {prix_min}€ min) - suspect"
        
        if annonce.prix > prix_max:
            return 0, f"Prix trop élevé ({annonce.prix}€ > {prix_max}€ max)"
        
        # Calcul du score basé sur position dans la fourchette
        # Plus le prix est bas, meilleur est le score
        range_total = prix_max - prix_min
        if range_total <= 0:
            return int(max_pts * 0.5), "Fourchette prix invalide"
        
        position = (prix_max - annonce.prix) / range_total
        score = int(max_pts * position)
        
        # Bonus si bien en dessous du prix marché
        if prix_marche and annonce.prix < prix_marche * 0.8:
            bonus = int(max_pts * 0.2)
            score = min(max_pts, score + bonus)
            detail = f"{annonce.prix}€ (-{int((1 - annonce.prix/prix_marche) * 100)}% vs marché {prix_marche}€)"
        else:
            detail = f"{annonce.prix}€ (fourchette {prix_min}-{prix_max}€)"
        
        return score, detail
    
    def _score_km(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, str]:
        """
        Score kilométrage (max 30 pts).
        Basé sur position dans la plage idéale.
        """
        max_pts = self.weights.get("km", 30)
        
        if annonce.kilometrage is None:
            return int(max_pts * 0.3), "Km non renseigné"
        
        criteres = vehicle_config.get("criteres", {})
        
        km_min = criteres.get("km_min", 50000)
        km_max = criteres.get("km_max", 200000)
        km_ideal_min = criteres.get("km_ideal_min", km_min)
        km_ideal_max = criteres.get("km_ideal_max", km_max - 30000)
        
        km = annonce.kilometrage
        
        # Trop peu de km = suspect (compteur?)
        if km < km_min:
            return int(max_pts * 0.4), f"{km:,} km < {km_min:,} km min - suspect".replace(",", " ")
        
        # Trop de km = hors cible
        if km > km_max:
            return 0, f"{km:,} km > {km_max:,} km max".replace(",", " ")
        
        # Dans la plage idéale = score max
        if km_ideal_min <= km <= km_ideal_max:
            return max_pts, f"{km:,} km (idéal {km_ideal_min:,}-{km_ideal_max:,})".replace(",", " ")
        
        # Entre min et ideal_min = bon score
        if km < km_ideal_min:
            ratio = (km - km_min) / (km_ideal_min - km_min) if km_ideal_min > km_min else 1
            score = int(max_pts * (0.7 + 0.3 * ratio))
            return score, f"{km:,} km (sous idéal)".replace(",", " ")
        
        # Entre ideal_max et max = score décroissant
        if km > km_ideal_max:
            ratio = (km_max - km) / (km_max - km_ideal_max) if km_max > km_ideal_max else 0
            score = int(max_pts * ratio * 0.7)
            return score, f"{km:,} km (au-dessus idéal)".replace(",", " ")
        
        return int(max_pts * 0.5), f"{km:,} km".replace(",", " ")
    
    def _score_freshness(self, annonce: Annonce) -> tuple[int, str]:
        """
        Score fraîcheur (max 10 pts).
        Basé sur l'âge de l'annonce.
        """
        max_pts = self.weights.get("freshness", 10)
        
        if not annonce.published_at:
            return int(max_pts * 0.5), "Date publication inconnue"
        
        now = datetime.now(timezone.utc)
        age = now - annonce.published_at
        hours = age.total_seconds() / 3600
        
        if hours < 1:
            return max_pts, "< 1h (très frais)"
        elif hours < 6:
            return int(max_pts * 0.9), f"{int(hours)}h"
        elif hours < 24:
            return int(max_pts * 0.7), f"{int(hours)}h"
        elif hours < 48:
            return int(max_pts * 0.5), "1-2 jours"
        elif hours < 168:  # 1 semaine
            return int(max_pts * 0.3), f"{int(hours/24)} jours"
        else:
            return 0, f"> 1 semaine ({int(hours/24)} jours)"
    
    def _score_keywords(self, annonce: Annonce) -> tuple[int, str]:
        """
        Score mots-clés opportunité (max 15 pts).
        """
        max_pts = self.weights.get("keywords", 15)
        
        text_to_check = " ".join([
            annonce.titre or "",
            annonce.description or "",
        ]).lower()
        
        total_bonus = 0
        found_keywords = []
        
        for kw_id, kw_config in self.keywords_opportunite.items():
            patterns = kw_config.get("patterns", [])
            bonus = kw_config.get("bonus", 5)
            
            for pattern in patterns:
                if pattern.lower() in text_to_check:
                    total_bonus += bonus
                    found_keywords.append(kw_id)
                    break  # Un seul match par catégorie
        
        annonce.keywords_opportunite = found_keywords
        
        score = min(max_pts, total_bonus)
        detail = ", ".join(found_keywords) if found_keywords else "Aucun"
        
        return score, detail
    
    def _score_bonus(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, str]:
        """
        Score bonus divers (max 5 pts).
        - Département prioritaire
        - Particulier vs pro
        - Bonus véhicule (stepway, etc.)
        """
        max_pts = self.weights.get("bonus", 5)
        bonuses = []
        total = 0
        
        # Bonus département
        dept = annonce.departement
        if dept:
            tier1 = self.dept_priority.get("tier1", [])
            tier2 = self.dept_priority.get("tier2", [])
            tier3 = self.dept_priority.get("tier3", [])
            
            if dept in tier1:
                total += 3
                bonuses.append(f"Dept {dept} (T1)")
            elif dept in tier2:
                total += 2
                bonuses.append(f"Dept {dept} (T2)")
            elif dept in tier3:
                total += 1
                bonuses.append(f"Dept {dept} (T3)")
        
        # Bonus particulier
        if annonce.seller_type == SellerType.PARTICULIER:
            total += 2
            bonuses.append("Particulier")
        elif annonce.seller_type == SellerType.PROFESSIONNEL:
            total -= 1
            bonuses.append("Pro (-1)")
        
        # Bonus spécifiques au véhicule
        vehicle_bonus = vehicle_config.get("bonus", {})
        text = f"{annonce.titre} {annonce.version}".lower()
        
        for bonus_name, bonus_value in vehicle_bonus.items():
            if bonus_name.lower() in text:
                total += min(2, bonus_value // 100)
                bonuses.append(bonus_name)
        
        score = max(0, min(max_pts, total))
        detail = ", ".join(bonuses) if bonuses else "Aucun"
        
        return score, detail
    
    def _score_risks(self, annonce: Annonce) -> tuple[int, str]:
        """
        Pénalités risques (valeur négative).
        Détecte les problèmes et estime les coûts.
        """
        text_to_check = " ".join([
            annonce.titre or "",
            annonce.description or "",
        ]).lower()
        
        total_penalty = 0
        found_risks = []
        total_cost = 0
        
        for risk_id, risk_config in self.keywords_risque.items():
            patterns = risk_config.get("patterns", [])
            penalty = risk_config.get("penalty", -10)
            cost = risk_config.get("cost_estimate", 0)
            
            for pattern in patterns:
                if pattern.lower() in text_to_check:
                    total_penalty += penalty  # Déjà négatif
                    total_cost += cost
                    found_risks.append(f"{risk_id} ({penalty}pts, ~{cost}€)")
                    break
        
        annonce.keywords_risque = [r.split(" ")[0] for r in found_risks]
        annonce.repair_cost_estimate = total_cost
        
        detail = ", ".join(found_risks) if found_risks else "Aucun risque détecté"
        
        return total_penalty, detail
    
    def _estimate_margin(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, int, int]:
        """
        Estime la marge potentielle.
        Retourne (margin_min, margin_max, repair_cost)
        """
        if annonce.prix is None:
            return 0, 0, 0
        
        estimation = vehicle_config.get("estimation", {})
        
        revente_min = estimation.get("prix_revente_min", annonce.prix + 500)
        revente_max = estimation.get("prix_revente_max", annonce.prix + 1500)
        
        repair_cost = annonce.repair_cost_estimate or 0
        
        margin_min = revente_min - annonce.prix - repair_cost
        margin_max = revente_max - annonce.prix - repair_cost
        
        return max(0, margin_min), max(0, margin_max), repair_cost


# Instance globale
_scoring_service: Optional[ScoringService] = None


def get_scoring_service() -> ScoringService:
    """Retourne l'instance du service de scoring"""
    global _scoring_service
    if _scoring_service is None:
        _scoring_service = ScoringService()
    return _scoring_service
