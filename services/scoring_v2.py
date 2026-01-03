"""
Scoring Service V3 - Calcul de score explicable amélioré
- Regex normalisé pour mots-clés (via KeywordMatcher)
- Prix très bas = opportunité (pas pénalisé) + flag "à vérifier"
- Marge nette basée sur coûts réels + sévérité
- Bonus département cohérent avec YAML
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import yaml

from models.annonce_v2 import Annonce, ScoreBreakdown
from models.enums import AlertLevel, SellerType, AnnonceStatus
from config.settings import CONFIG_DIR
from services.keywords import get_keyword_matcher, KeywordMatcher


def load_yaml(filename: str) -> dict[str, Any]:
    """Charge un fichier YAML de config"""
    path = CONFIG_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@dataclass
class PriceAnalysis:
    """Analyse détaillée du prix"""
    score: int
    detail: str
    is_suspicious: bool = False  # Prix anormalement bas
    needs_verification: bool = False  # Flag "à vérifier"
    discount_vs_market: float = 0.0  # % sous le marché


class ScoringServiceV3:
    """
    Service de scoring V3 - Améliorations pépites
    
    Changements majeurs:
    - KeywordMatcher avec regex normalisé (accents, frontières)
    - Prix très bas = score élevé + flag "à vérifier" (pas pénalisé)
    - Marge nette = revente - prix - coûts_risques - buffer
    - Sévérité risques influence le niveau d'alerte
    - Bonus département augmenté (poids 10 au lieu de 5)
    """
    
    def __init__(self):
        # Charger les configs YAML
        self.vehicles_config = load_yaml("vehicles.yaml")
        
        # Poids du scoring (ajustés)
        self.weights = self.vehicles_config.get("scoring_weights", {
            "prix": 35,      # Réduit légèrement
            "km": 25,        # Réduit légèrement
            "keywords": 15,  # Opportunités
            "freshness": 10,
            "bonus": 10,     # Augmenté (inclut département)
            "margin": 5      # Nouveau: bonus si marge nette élevée
        })
        
        # Véhicules cibles
        self.vehicles = self.vehicles_config.get("vehicles", {})
        
        # Départements prioritaires avec vrais bonus
        self.dept_priority = self.vehicles_config.get("departements_prioritaires", {})
        
        # KeywordMatcher avec regex
        self.keyword_matcher = get_keyword_matcher()
        
        # Buffer de sécurité pour marge
        self.margin_buffer = 200  # € de marge de sécurité
    
    def calculate_score(self, annonce: Annonce) -> ScoreBreakdown:
        """
        Calcule le score complet avec breakdown.
        """
        breakdown = ScoreBreakdown()
        
        # 1. Identifier le véhicule cible
        vehicle_id, vehicle_config = self._identify_vehicle(annonce)
        if not vehicle_config:
            breakdown.total = 0
            breakdown.prix_detail = "Véhicule non ciblé"
            return breakdown
        
        annonce.vehicule_cible_id = vehicle_id
        
        # 2. PASSE UNIQUE KEYWORDS - calculer risques/opportunités AVANT tout le reste
        # Cela résout le bug où _score_prix_v2 vérifiait keywords_risque vide
        text_full = f"{annonce.titre or ''} {annonce.description or ''} {annonce.version or ''}"
        
        # Vérifier exclusions
        excluded, exclude_reason = self.keyword_matcher.is_excluded(text_full)
        if excluded:
            breakdown.total = 0
            breakdown.risk_detail = f"EXCLU: {exclude_reason}"
            annonce.status = AnnonceStatus.EXCLUE
            annonce.ignore_reason = exclude_reason
            return breakdown
        
        # Passe unique: opportunités + risques + coûts
        (kw_bonus, kw_penalty, kw_cost_estimate, 
         opportunity_ids, risk_ids) = self.keyword_matcher.calculate_scores(text_full)
        max_severity = self.keyword_matcher.get_severity_max(text_full)
        
        # Stocker dans l'annonce AVANT le calcul du prix
        annonce.keywords_opportunite = opportunity_ids
        annonce.keywords_risque = risk_ids
        annonce.repair_cost_estimate = kw_cost_estimate
        
        # 3. Calculer les composantes (maintenant keywords_risque est peuplé)
        price_analysis = self._score_prix_v2(annonce, vehicle_config)
        breakdown.prix_score = price_analysis.score
        breakdown.prix_detail = price_analysis.detail
        
        breakdown.km_score, breakdown.km_detail = self._score_km(
            annonce, vehicle_config
        )
        
        breakdown.freshness_score, breakdown.freshness_detail = self._score_freshness(
            annonce
        )
        
        # Mots-clés opportunité (utilise les résultats de la passe unique)
        breakdown.keywords_score = min(self.weights.get("keywords", 15), kw_bonus)
        breakdown.keywords_detail = ", ".join(opportunity_ids) if opportunity_ids else "Aucun"
        
        breakdown.bonus_score, breakdown.bonus_detail = self._score_bonus_v2(
            annonce, vehicle_config
        )
        
        # Risques (utilise les résultats de la passe unique)
        breakdown.risk_penalty = kw_penalty
        if risk_ids:
            breakdown.risk_detail = f"{', '.join(risk_ids)} (~{kw_cost_estimate}€)"
            if max_severity == "critical":
                breakdown.risk_detail = f"⚠️ CRITIQUE: {breakdown.risk_detail}"
        else:
            breakdown.risk_detail = "Aucun risque détecté"
        
        # 4. Calculer marge nette
        breakdown.margin_min, breakdown.margin_max, breakdown.repair_cost_estimate = (
            self._estimate_margin_v2(annonce, vehicle_config)
        )
        
        # Bonus marge (si marge nette élevée)
        margin_bonus = self._score_margin_bonus(breakdown.margin_min)
        
        # 5. Calculer le total
        raw_score = (
            breakdown.prix_score +
            breakdown.km_score +
            breakdown.freshness_score +
            breakdown.keywords_score +
            breakdown.bonus_score +
            breakdown.risk_penalty +  # Négatif
            margin_bonus
        )
        
        breakdown.total = max(0, min(100, raw_score))
        
        # 6. Ajuster alert_level selon sévérité risques
        if max_severity == "critical" and breakdown.total >= 60:
            # Risque critique = downgrade à "surveiller" sauf si marge énorme
            if breakdown.margin_min < 1000:
                breakdown.total = min(breakdown.total, 59)
        
        # 7. Ajouter flag "à vérifier" si prix suspect
        if price_analysis.needs_verification:
            if not annonce.keywords_risque:
                annonce.keywords_risque = []
            if "prix_a_verifier" not in annonce.keywords_risque:
                annonce.keywords_risque.append("prix_a_verifier")
        
        # 8. Mettre à jour l'annonce
        annonce.update_score(breakdown.total, breakdown)
        
        return breakdown
    
    def _identify_vehicle(
        self, 
        annonce: Annonce
    ) -> tuple[str, Optional[dict[str, Any]]]:
        """
        Identifie le véhicule cible correspondant à l'annonce.
        """
        if not annonce.marque or not annonce.modele:
            return "", None
        
        annonce_marque = annonce.marque.lower().strip()
        annonce_modele = annonce.modele.lower().strip()
        annonce_titre = (annonce.titre or "").lower()
        annonce_version = (annonce.version or "").lower()
        
        for vehicle_id, config in self.vehicles.items():
            config_marque = config.get("marque", "").lower()
            if config_marque not in annonce_marque and annonce_marque not in config_marque:
                continue
            
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
                    pattern_clean = pattern.replace("^", "").replace("$", "").replace("\\s", " ")
                    if pattern_clean.lower() in annonce_modele:
                        modele_match = True
                        break
            
            if not modele_match:
                continue
            
            config_carburant = config.get("carburant")
            if config_carburant:
                annonce_carburant = str(annonce.carburant.value).lower()
                if config_carburant.lower() not in annonce_carburant:
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
    
    def _score_prix_v2(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> PriceAnalysis:
        """
        Score prix V2 - Ne pénalise PAS les prix très bas.
        Prix bas = opportunité potentielle + flag "à vérifier"
        """
        max_pts = self.weights.get("prix", 35)
        
        if annonce.prix is None:
            return PriceAnalysis(score=0, detail="Prix non renseigné")
        
        criteres = vehicle_config.get("criteres", {})
        estimation = vehicle_config.get("estimation", {})
        
        prix_min = criteres.get("prix_min", 1000)
        prix_max = criteres.get("prix_max", 5000)
        prix_marche = estimation.get("prix_marche_median") or annonce.prix_marche_estime or ((prix_min + prix_max) / 2)
        
        # Prix au-dessus du max = score 0
        if annonce.prix > prix_max:
            return PriceAnalysis(
                score=0,
                detail=f"Prix trop élevé ({annonce.prix}€ > {prix_max}€ max)"
            )
        
        # Prix très bas = OPPORTUNITÉ (pas pénalisé!)
        if annonce.prix < prix_min:
            discount = (1 - annonce.prix / prix_marche) * 100 if prix_marche else 0
            
            # Score élevé mais flag "à vérifier"
            # Plus c'est bas, plus c'est intéressant (mais suspect)
            score = int(max_pts * 0.9)  # Score élevé!
            
            # Vérifier si vraiment suspect ou juste bonne affaire
            has_risk_keywords = bool(annonce.keywords_risque)
            has_images = bool(annonce.images_urls)
            is_particulier = annonce.seller_type == SellerType.PARTICULIER
            
            needs_verif = True
            if has_images and is_particulier and not has_risk_keywords:
                # Probablement légitime
                score = max_pts
                needs_verif = False
                detail = f"🔥 {annonce.prix}€ (-{int(discount)}% marché) - Très bonne affaire!"
            else:
                detail = f"⚠️ {annonce.prix}€ (-{int(discount)}% marché) - À VÉRIFIER (prix anormal)"
            
            return PriceAnalysis(
                score=score,
                detail=detail,
                is_suspicious=True,
                needs_verification=needs_verif,
                discount_vs_market=discount
            )
        
        # Prix dans la fourchette normale
        range_total = prix_max - prix_min
        if range_total <= 0:
            return PriceAnalysis(score=int(max_pts * 0.5), detail="Fourchette prix invalide")
        
        # Plus le prix est bas, meilleur est le score
        position = (prix_max - annonce.prix) / range_total
        score = int(max_pts * position)
        
        # Bonus si bien en dessous du prix marché
        discount = 0
        if prix_marche and annonce.prix < prix_marche * 0.85:
            discount = (1 - annonce.prix / prix_marche) * 100
            bonus = int(max_pts * 0.15)
            score = min(max_pts, score + bonus)
            detail = f"{annonce.prix}€ (-{int(discount)}% vs marché {int(prix_marche)}€)"
        else:
            detail = f"{annonce.prix}€ (fourchette {prix_min}-{prix_max}€)"
        
        return PriceAnalysis(
            score=score,
            detail=detail,
            discount_vs_market=discount
        )
    
    def _score_km(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, str]:
        """Score kilométrage"""
        max_pts = self.weights.get("km", 25)
        
        if annonce.kilometrage is None:
            return int(max_pts * 0.3), "Km non renseigné"
        
        criteres = vehicle_config.get("criteres", {})
        
        km_min = criteres.get("km_min", 50000)
        km_max = criteres.get("km_max", 200000)
        km_ideal_min = criteres.get("km_ideal_min", km_min)
        km_ideal_max = criteres.get("km_ideal_max", km_max - 30000)
        
        km = annonce.kilometrage
        
        if km < km_min:
            return int(max_pts * 0.5), f"{km:,} km < {km_min:,} km - bas (vérifier)".replace(",", " ")
        
        if km > km_max:
            return 0, f"{km:,} km > {km_max:,} km max".replace(",", " ")
        
        if km_ideal_min <= km <= km_ideal_max:
            return max_pts, f"{km:,} km (idéal)".replace(",", " ")
        
        if km < km_ideal_min:
            ratio = (km - km_min) / (km_ideal_min - km_min) if km_ideal_min > km_min else 1
            score = int(max_pts * (0.7 + 0.3 * ratio))
            return score, f"{km:,} km".replace(",", " ")
        
        if km > km_ideal_max:
            ratio = (km_max - km) / (km_max - km_ideal_max) if km_max > km_ideal_max else 0
            score = int(max_pts * ratio * 0.7)
            return score, f"{km:,} km (élevé)".replace(",", " ")
        
        return int(max_pts * 0.5), f"{km:,} km".replace(",", " ")
    
    def _score_freshness(self, annonce: Annonce) -> tuple[int, str]:
        """Score fraîcheur"""
        max_pts = self.weights.get("freshness", 10)
        
        if not annonce.published_at:
            return int(max_pts * 0.5), "Date inconnue"
        
        now = datetime.now(timezone.utc)
        age = now - annonce.published_at
        hours = age.total_seconds() / 3600
        
        if hours < 1:
            return max_pts, "< 1h 🔥"
        elif hours < 3:
            return int(max_pts * 0.95), f"{int(hours)}h"
        elif hours < 6:
            return int(max_pts * 0.85), f"{int(hours)}h"
        elif hours < 12:
            return int(max_pts * 0.7), f"{int(hours)}h"
        elif hours < 24:
            return int(max_pts * 0.5), f"{int(hours)}h"
        elif hours < 48:
            return int(max_pts * 0.3), "1-2j"
        elif hours < 168:
            return int(max_pts * 0.15), f"{int(hours/24)}j"
        else:
            return 0, f"> 1 sem"
    
    def _score_keywords_v2(self, annonce: Annonce) -> tuple[int, str]:
        """
        Score mots-clés via KeywordMatcher (regex normalisé).
        """
        max_pts = self.weights.get("keywords", 15)
        
        text = f"{annonce.titre or ''} {annonce.description or ''}"
        
        bonus, _, _, opportunity_ids, _ = self.keyword_matcher.calculate_scores(text)
        
        annonce.keywords_opportunite = opportunity_ids
        
        score = min(max_pts, bonus)
        detail = ", ".join(opportunity_ids) if opportunity_ids else "Aucun"
        
        return score, detail
    
    def _score_bonus_v2(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, str]:
        """
        Score bonus V2 - Département avec vrais bonus significatifs.
        Poids augmenté à 10 pts max.
        """
        max_pts = self.weights.get("bonus", 10)
        bonuses = []
        total = 0
        
        # Bonus département (significatif maintenant)
        dept = annonce.departement
        if dept:
            tier1 = self.dept_priority.get("tier1", [])
            tier2 = self.dept_priority.get("tier2", [])
            tier3 = self.dept_priority.get("tier3", [])
            
            if dept in tier1:
                total += 5  # +5 au lieu de +3
                bonuses.append(f"📍 {dept} (proche)")
            elif dept in tier2:
                total += 3  # +3 au lieu de +2
                bonuses.append(f"📍 {dept}")
            elif dept in tier3:
                total += 1
                bonuses.append(f"{dept}")
        
        # Bonus particulier
        if annonce.seller_type == SellerType.PARTICULIER:
            total += 3
            bonuses.append("Particulier")
        elif annonce.seller_type == SellerType.PROFESSIONNEL:
            total -= 1
            bonuses.append("Pro")
        
        # Bonus photos (indicateur de sérieux)
        if annonce.images_urls and len(annonce.images_urls) >= 5:
            total += 1
            bonuses.append(f"{len(annonce.images_urls)} photos")
        
        # Bonus spécifiques au véhicule
        vehicle_bonus = vehicle_config.get("bonus", {})
        text = f"{annonce.titre} {annonce.version}".lower()
        
        for bonus_name, bonus_value in vehicle_bonus.items():
            if bonus_name.lower() in text:
                pts = min(2, bonus_value // 100) if isinstance(bonus_value, int) else 1
                total += pts
                bonuses.append(bonus_name)
        
        score = max(0, min(max_pts, total))
        detail = ", ".join(bonuses) if bonuses else "Aucun"
        
        return score, detail
    
    def _score_risks_v2(self, annonce: Annonce) -> tuple[int, str, str]:
        """
        Pénalités risques via KeywordMatcher.
        Retourne aussi la sévérité max.
        """
        text = f"{annonce.titre or ''} {annonce.description or ''}"
        
        _, penalty, cost_estimate, _, risk_ids = self.keyword_matcher.calculate_scores(text)
        max_severity = self.keyword_matcher.get_severity_max(text)
        
        annonce.keywords_risque = risk_ids
        annonce.repair_cost_estimate = cost_estimate
        
        # Construire le détail
        if risk_ids:
            detail = f"{', '.join(risk_ids)} (~{cost_estimate}€)"
            if max_severity == "critical":
                detail = f"⚠️ CRITIQUE: {detail}"
        else:
            detail = "Aucun risque détecté"
        
        return penalty, detail, max_severity
    
    def _score_margin_bonus(self, margin_min: int) -> int:
        """Bonus si marge nette élevée"""
        max_pts = self.weights.get("margin", 5)
        
        if margin_min >= 1500:
            return max_pts
        elif margin_min >= 1000:
            return int(max_pts * 0.7)
        elif margin_min >= 500:
            return int(max_pts * 0.4)
        return 0
    
    def _estimate_margin_v2(
        self, 
        annonce: Annonce, 
        vehicle_config: dict[str, Any]
    ) -> tuple[int, int, int]:
        """
        Estime la marge nette.
        Marge = Revente - Prix - Coûts_risques - Buffer
        """
        if annonce.prix is None:
            return 0, 0, 0
        
        estimation = vehicle_config.get("estimation", {})
        
        revente_min = estimation.get("prix_revente_min", annonce.prix + 500)
        revente_max = estimation.get("prix_revente_max", annonce.prix + 1500)
        
        repair_cost = annonce.repair_cost_estimate or 0
        
        # Marge nette avec buffer
        margin_min = revente_min - annonce.prix - repair_cost - self.margin_buffer
        margin_max = revente_max - annonce.prix - repair_cost - self.margin_buffer
        
        return max(0, margin_min), max(0, margin_max), repair_cost


# Instance globale
_scoring_service_v3: Optional[ScoringServiceV3] = None


def get_scoring_service_v3() -> ScoringServiceV3:
    """Retourne l'instance du service de scoring V3"""
    global _scoring_service_v3
    if _scoring_service_v3 is None:
        _scoring_service_v3 = ScoringServiceV3()
    return _scoring_service_v3
