"""
Analyzer Service - Analyse avancée des annonces
"""

import re
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from models.annonce import Annonce
from config import VEHICULES_CIBLES, MOTS_CLES_OPPORTUNITE, MOTS_CLES_EXCLUSION
from utils.logger import get_logger

logger = get_logger(__name__)


class AnalyzerService:
    """Service d'analyse avancée des annonces"""
    
    # Problèmes courants et coûts estimés de réparation
    PROBLEMES_COUTS = {
        "embrayage": (400, 800),
        "distribution": (400, 700),
        "turbo": (800, 1500),
        "injecteur": (150, 400),
        "vanne egr": (200, 500),
        "fap": (300, 1000),
        "volant moteur": (500, 1000),
        "demarreur": (150, 350),
        "alternateur": (200, 400),
        "radiateur": (150, 400),
        "climatisation": (200, 600),
        "boite de vitesse": (800, 2000),
        "suspension": (200, 600),
        "freins": (150, 400),
        "pneus": (200, 400),
    }
    
    # Patterns pour extraire des informations
    PATTERNS = {
        "telephone": [
            r"(\+33|0033|0)[1-9][\s\.\-]?(\d{2}[\s\.\-]?){4}",
            r"tel[\s:]*(\d[\d\s\.\-]{9,})",
        ],
        "email": [
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        ],
        "immatriculation": [
            r"[A-Z]{2}[\s\-]?\d{3}[\s\-]?[A-Z]{2}",
        ],
    }
    
    def analyser(self, annonce: Annonce) -> Dict:
        """Analyse complète d'une annonce"""
        resultats = {
            "problemes_detectes": [],
            "cout_reparation_estime": (0, 0),
            "contacts_extraits": {},
            "qualite_annonce": 0,
            "alertes": [],
            "opportunites": [],
        }
        
        texte = f"{annonce.titre or ''} {annonce.description or ''}".lower()
        
        # Détecter les problèmes
        resultats["problemes_detectes"] = self._detecter_problemes(texte)
        resultats["cout_reparation_estime"] = self._estimer_couts(resultats["problemes_detectes"])
        
        # Extraire les contacts
        resultats["contacts_extraits"] = self._extraire_contacts(annonce.description or "")
        
        # Évaluer la qualité
        resultats["qualite_annonce"] = self._evaluer_qualite(annonce)
        
        # Détecter les alertes et opportunités
        resultats["alertes"] = self._detecter_alertes(annonce, texte)
        resultats["opportunites"] = self._detecter_opportunites(annonce, texte)
        
        return resultats
    
    def _detecter_problemes(self, texte: str) -> List[Dict]:
        """Détecte les problèmes mentionnés dans le texte"""
        problemes = []
        
        for probleme, (cout_min, cout_max) in self.PROBLEMES_COUTS.items():
            if probleme in texte:
                problemes.append({
                    "type": probleme,
                    "cout_estime": (cout_min, cout_max)
                })
        
        # Patterns spécifiques
        patterns_problemes = [
            (r"voyant\s+(allumé|orange|moteur)", "voyant moteur", (50, 500)),
            (r"fume\s*(noir|blanc|bleu)?", "fumée échappement", (100, 800)),
            (r"(perte|manque)\s+de?\s*puissance", "perte puissance", (100, 1000)),
            (r"ct\s+(à\s+faire|refusé)", "contrôle technique", (100, 500)),
            (r"contre[\s\-]?visite", "contre-visite", (100, 500)),
        ]
        
        for pattern, nom, cout in patterns_problemes:
            if re.search(pattern, texte):
                if not any(p["type"] == nom for p in problemes):
                    problemes.append({
                        "type": nom,
                        "cout_estime": cout
                    })
        
        return problemes
    
    def _estimer_couts(self, problemes: List[Dict]) -> Tuple[int, int]:
        """Estime le coût total de réparation"""
        cout_min = sum(p["cout_estime"][0] for p in problemes)
        cout_max = sum(p["cout_estime"][1] for p in problemes)
        return (cout_min, cout_max)
    
    def _extraire_contacts(self, texte: str) -> Dict:
        """Extrait les informations de contact"""
        contacts = {}
        
        # Téléphone
        for pattern in self.PATTERNS["telephone"]:
            match = re.search(pattern, texte, re.I)
            if match:
                tel = re.sub(r"[^\d+]", "", match.group())
                if len(tel) >= 10:
                    contacts["telephone"] = tel
                    break
        
        # Email
        for pattern in self.PATTERNS["email"]:
            match = re.search(pattern, texte, re.I)
            if match:
                contacts["email"] = match.group()
                break
        
        return contacts
    
    def _evaluer_qualite(self, annonce: Annonce) -> int:
        """Évalue la qualité de l'annonce sur 100"""
        score = 50  # Base
        
        # Photos
        nb_photos = len(annonce.images_urls)
        if nb_photos >= 10:
            score += 20
        elif nb_photos >= 5:
            score += 15
        elif nb_photos >= 3:
            score += 10
        elif nb_photos >= 1:
            score += 5
        else:
            score -= 10
        
        # Description
        desc_len = len(annonce.description or "")
        if desc_len >= 500:
            score += 15
        elif desc_len >= 200:
            score += 10
        elif desc_len >= 100:
            score += 5
        else:
            score -= 5
        
        # Informations complètes
        if annonce.kilometrage:
            score += 5
        if annonce.annee:
            score += 5
        if annonce.motorisation:
            score += 5
        
        return max(0, min(100, score))
    
    def _detecter_alertes(self, annonce: Annonce, texte: str) -> List[str]:
        """Détecte les alertes (points négatifs)"""
        alertes = []
        
        # Mots-clés d'exclusion
        for mot in MOTS_CLES_EXCLUSION:
            if mot.lower() in texte:
                alertes.append(f"⚠️ Mot-clé exclusion: '{mot}'")
        
        # Prix trop bas (arnaque potentielle?)
        if annonce.prix and annonce.prix < 1000:
            alertes.append("⚠️ Prix très bas - vérifier authenticité")
        
        # Vendeur pro déguisé
        patterns_pro = ["stock", "plusieurs véhicules", "parc auto", "négociant"]
        for p in patterns_pro:
            if p in texte:
                alertes.append(f"⚠️ Possible professionnel: '{p}'")
                break
        
        # Kilométrage suspect
        if annonce.kilometrage and annonce.annee:
            km_par_an = annonce.kilometrage / (datetime.now().year - annonce.annee + 1)
            if km_par_an < 3000:
                alertes.append("⚠️ Kilométrage anormalement bas")
            elif km_par_an > 35000:
                alertes.append("⚠️ Kilométrage très élevé pour l'âge")
        
        return alertes
    
    def _detecter_opportunites(self, annonce: Annonce, texte: str) -> List[str]:
        """Détecte les opportunités (points positifs)"""
        opportunites = []
        
        # Mots-clés opportunité
        for mot in MOTS_CLES_OPPORTUNITE:
            if mot.lower() in texte:
                opportunites.append(f"✅ Mot-clé opportunité: '{mot}'")
        
        # Vente urgente
        if any(u in texte for u in ["urgent", "vite", "rapide", "départ"]):
            opportunites.append("✅ Vente urgente - négociation possible")
        
        # Stepway au prix Sandero
        if "stepway" in texte and annonce.prix and annonce.prix < 3500:
            opportunites.append("✅ Stepway à bon prix!")
        
        # Entretien récent
        if any(e in texte for e in ["distribution faite", "embrayage neuf", "pneus neufs", "ct ok"]):
            opportunites.append("✅ Entretien récent mentionné")
        
        # Première main
        if "première main" in texte or "1ère main" in texte:
            opportunites.append("✅ Première main")
        
        # Faible kilométrage pour diesel ZFE
        if annonce.carburant and "diesel" in annonce.carburant.lower():
            if annonce.departement in ["75", "92", "93", "94"]:
                opportunites.append("✅ Diesel en zone ZFE - propriétaire motivé")
        
        return opportunites
    
    def comparer_annonces(self, annonces: List[Annonce]) -> List[Dict]:
        """Compare plusieurs annonces similaires"""
        if len(annonces) < 2:
            return []
        
        comparaisons = []
        
        # Trier par score
        sorted_annonces = sorted(annonces, key=lambda a: a.score_rentabilite, reverse=True)
        
        meilleure = sorted_annonces[0]
        
        for annonce in sorted_annonces[1:]:
            diff = {
                "annonce": annonce,
                "diff_prix": (annonce.prix or 0) - (meilleure.prix or 0),
                "diff_km": (annonce.kilometrage or 0) - (meilleure.kilometrage or 0),
                "diff_score": annonce.score_rentabilite - meilleure.score_rentabilite,
            }
            comparaisons.append(diff)
        
        return comparaisons
    
    def resume_annonce(self, annonce: Annonce) -> str:
        """Génère un résumé textuel de l'analyse"""
        analyse = self.analyser(annonce)
        
        resume = [
            f"📊 ANALYSE: {annonce.marque} {annonce.modele}",
            f"Score: {annonce.score_rentabilite}/100",
            f"Qualité annonce: {analyse['qualite_annonce']}/100",
        ]
        
        if analyse["problemes_detectes"]:
            cout_min, cout_max = analyse["cout_reparation_estime"]
            resume.append(f"Problèmes: {len(analyse['problemes_detectes'])} ({cout_min}€-{cout_max}€)")
        
        if analyse["opportunites"]:
            resume.append(f"Opportunités: {len(analyse['opportunites'])}")
        
        if analyse["alertes"]:
            resume.append(f"⚠️ Alertes: {len(analyse['alertes'])}")
        
        return "\n".join(resume)
