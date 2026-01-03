"""
Normalize Service - Parsing et normalisation des données
Extrait et nettoie les informations des annonces brutes
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional, Tuple

from models.enums import Carburant, Boite, SellerType


class NormalizeService:
    """Service de normalisation des données d'annonces"""
    
    # Patterns regex compilés pour performance
    _PRICE_PATTERN = re.compile(r"(\d[\d\s\u202f\u00a0.,]*)\s*€")
    _KM_PATTERN = re.compile(r"(\d[\d\s\u202f\u00a0.,]*)\s*km", re.IGNORECASE)
    # Pattern année dynamique (jusqu'à année courante + 1)
    _CURRENT_YEAR = datetime.now().year
    _YEAR_PATTERN = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")  # 1980-2039
    _DEPT_PATTERN = re.compile(r"\b(\d{2})\d{3}\b|\((\d{2})\)")
    _PHONE_PATTERN = re.compile(r"(?:0|\+33)[1-9](?:[\s.-]?\d{2}){4}")
    _POWER_PATTERN = re.compile(r"(\d{2,3})\s*(?:ch|cv|hp)", re.IGNORECASE)
    
    def __init__(self):
        pass
    
    # === Texte ===
    
    def normalize_text(self, text: str | None) -> str:
        """Normalise un texte (minuscules, accents, espaces)"""
        if not text:
            return ""
        
        # Minuscules
        text = text.lower().strip()
        
        # Normaliser les espaces
        text = re.sub(r"\s+", " ", text)
        
        return text
    
    def remove_accents(self, text: str) -> str:
        """Supprime les accents d'un texte"""
        if not text:
            return ""
        
        # Décomposition NFD + suppression des marques diacritiques
        normalized = unicodedata.normalize("NFD", text)
        return "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    
    def clean_for_matching(self, text: str) -> str:
        """Nettoie un texte pour matching (alphanum uniquement)"""
        text = self.normalize_text(text)
        text = self.remove_accents(text)
        return re.sub(r"[^a-z0-9]", "", text)
    
    # === Prix ===
    
    def parse_price(self, text: str | None) -> Optional[int]:
        """
        Extrait le prix d'un texte.
        Gère les formats: 2 500€, 2500 €, 2.500€, 2,500€
        """
        if not text:
            return None
        
        match = self._PRICE_PATTERN.search(text)
        if not match:
            # Essayer sans symbole €
            cleaned = re.sub(r"[^\d]", "", text)
            if cleaned and 500 <= int(cleaned) <= 100000:
                return int(cleaned)
            return None
        
        price_str = match.group(1)
        # Nettoyer: garder uniquement les chiffres
        price_str = re.sub(r"[^\d]", "", price_str)
        
        if not price_str:
            return None
        
        price = int(price_str)
        
        # Validation: prix réaliste pour une voiture d'occasion
        if 100 <= price <= 100000:
            return price
        
        return None
    
    def format_price_fr(self, price: int | None) -> str:
        """Formate un prix en français (espaces)"""
        if price is None:
            return "N/C"
        return f"{price:,}".replace(",", " ") + " €"
    
    # === Kilométrage ===
    
    def parse_km(self, text: str | None) -> Optional[int]:
        """
        Extrait le kilométrage d'un texte.
        Gère les formats: 150 000 km, 150000km, 150.000 km
        """
        if not text:
            return None
        
        match = self._KM_PATTERN.search(text)
        if not match:
            return None
        
        km_str = match.group(1)
        km_str = re.sub(r"[^\d]", "", km_str)
        
        if not km_str:
            return None
        
        km = int(km_str)
        
        # Validation: km réaliste
        if 100 <= km <= 500000:
            return km
        
        return None
    
    def format_km_fr(self, km: int | None) -> str:
        """Formate un kilométrage en français"""
        if km is None:
            return "N/C"
        return f"{km:,}".replace(",", " ") + " km"
    
    # === Année ===
    
    def parse_year(self, text: str | None) -> Optional[int]:
        """Extrait l'année d'un texte"""
        if not text:
            return None
        
        matches = self._YEAR_PATTERN.findall(text)
        if not matches:
            return None
        
        # Prendre l'année la plus récente (souvent la plus pertinente)
        years = [int(y) for y in matches]
        
        # Filtrer les années réalistes (voitures) - dynamique
        max_year = self._CURRENT_YEAR + 1
        valid_years = [y for y in years if 1990 <= y <= max_year]
        
        if not valid_years:
            return None
        
        return max(valid_years)
    
    # === Département / Code Postal ===
    
    def parse_departement(self, text: str | None) -> Optional[str]:
        """Extrait le département d'un texte (code postal ou entre parenthèses)"""
        if not text:
            return None
        
        # Chercher code postal (5 chiffres)
        cp_match = re.search(r"\b(\d{5})\b", text)
        if cp_match:
            return cp_match.group(1)[:2]
        
        # Chercher département entre parenthèses
        paren_match = re.search(r"\((\d{2})\)", text)
        if paren_match:
            return paren_match.group(1)
        
        return None
    
    def parse_code_postal(self, text: str | None) -> Optional[str]:
        """Extrait le code postal d'un texte"""
        if not text:
            return None
        
        match = re.search(r"\b(\d{5})\b", text)
        if match:
            return match.group(1)
        
        return None
    
    # === Carburant ===
    
    def parse_carburant(self, text: str | None) -> Carburant:
        """Détecte le type de carburant"""
        return Carburant.from_string(text)
    
    # === Boîte de vitesses ===
    
    def parse_boite(self, text: str | None) -> Boite:
        """Détecte le type de boîte"""
        return Boite.from_string(text)
    
    # === Puissance ===
    
    def parse_puissance(self, text: str | None) -> Optional[int]:
        """Extrait la puissance en chevaux"""
        if not text:
            return None
        
        match = self._POWER_PATTERN.search(text)
        if match:
            power = int(match.group(1))
            if 40 <= power <= 500:
                return power
        
        return None
    
    # === Vendeur ===
    
    def parse_seller_type(self, text: str | None) -> SellerType:
        """Détecte le type de vendeur"""
        if not text:
            return SellerType.UNKNOWN
        
        text_lower = text.lower()
        
        pro_patterns = [
            "professionnel", "pro", "garage", "concessionnaire",
            "marchand", "négociant", "société", "sarl", "sas", "eurl"
        ]
        
        particulier_patterns = [
            "particulier", "privé", "private", "owner"
        ]
        
        for pattern in pro_patterns:
            if pattern in text_lower:
                return SellerType.PROFESSIONNEL
        
        for pattern in particulier_patterns:
            if pattern in text_lower:
                return SellerType.PARTICULIER
        
        return SellerType.UNKNOWN
    
    # === Téléphone ===
    
    def extract_phone(self, text: str | None) -> Optional[str]:
        """Extrait un numéro de téléphone"""
        if not text:
            return None
        
        match = self._PHONE_PATTERN.search(text)
        if match:
            phone = match.group(0)
            # Nettoyer le format
            phone = re.sub(r"[\s.-]", "", phone)
            return phone
        
        return None
    
    # === Marque / Modèle ===
    
    def normalize_marque(self, marque: str | None) -> str:
        """Normalise le nom d'une marque"""
        if not marque:
            return ""
        
        marque = marque.strip().title()
        
        # Corrections courantes
        corrections = {
            "Volkswagen": ["Vw", "Volks"],
            "Mercedes-Benz": ["Mercedes", "Mb"],
            "Alfa Romeo": ["Alfa"],
            "Citroën": ["Citroen"],
        }
        
        marque_clean = self.clean_for_matching(marque)
        for correct, variants in corrections.items():
            for variant in variants:
                if self.clean_for_matching(variant) == marque_clean:
                    return correct
        
        return marque
    
    def normalize_modele(self, modele: str | None) -> str:
        """Normalise le nom d'un modèle"""
        if not modele:
            return ""
        
        modele = modele.strip()
        
        # Supprimer les infos de version/motorisation du modèle
        modele = re.sub(r"\d+\.\d+\s*(hdi|dci|tdi|vti|tce|dti|cdti|jtd).*", "", modele, flags=re.IGNORECASE)
        modele = re.sub(r"\d+\s*(ch|cv).*", "", modele, flags=re.IGNORECASE)
        
        return modele.strip().title()
    
    # === Titre / Version ===
    
    # Mapping modèle -> marque pour inférence
    _MODELE_TO_MARQUE = {
        # Peugeot
        "106": "Peugeot", "107": "Peugeot", "108": "Peugeot",
        "206": "Peugeot", "207": "Peugeot", "208": "Peugeot",
        "306": "Peugeot", "307": "Peugeot", "308": "Peugeot",
        "406": "Peugeot", "407": "Peugeot", "408": "Peugeot",
        "2008": "Peugeot", "3008": "Peugeot", "5008": "Peugeot",
        "Partner": "Peugeot", "Expert": "Peugeot",
        # Renault
        "Clio": "Renault", "Megane": "Renault", "Twingo": "Renault",
        "Scenic": "Renault", "Captur": "Renault", "Kadjar": "Renault",
        "Laguna": "Renault", "Kangoo": "Renault", "Trafic": "Renault",
        # Citroën
        "C1": "Citroën", "C2": "Citroën", "C3": "Citroën",
        "C4": "Citroën", "C5": "Citroën", "C6": "Citroën",
        "Berlingo": "Citroën", "Picasso": "Citroën", "Saxo": "Citroën",
        # Dacia
        "Sandero": "Dacia", "Logan": "Dacia", "Duster": "Dacia",
        "Stepway": "Dacia", "Dokker": "Dacia", "Lodgy": "Dacia",
        # Ford
        "Fiesta": "Ford", "Focus": "Ford", "Ka": "Ford",
        "Mondeo": "Ford", "Kuga": "Ford", "C-Max": "Ford",
        # Volkswagen
        "Polo": "Volkswagen", "Golf": "Volkswagen", "Passat": "Volkswagen",
        "Tiguan": "Volkswagen", "Touran": "Volkswagen", "Caddy": "Volkswagen",
        # Toyota
        "Yaris": "Toyota", "Aygo": "Toyota", "Corolla": "Toyota",
        "Auris": "Toyota", "RAV4": "Toyota", "C-HR": "Toyota",
        # Opel
        "Corsa": "Opel", "Astra": "Opel", "Meriva": "Opel",
        "Mokka": "Opel", "Zafira": "Opel", "Insignia": "Opel",
        # Fiat
        "Punto": "Fiat", "Panda": "Fiat", "500": "Fiat",
        "Tipo": "Fiat", "Doblo": "Fiat", "Bravo": "Fiat",
    }
    
    def parse_title(self, titre: str | None) -> Tuple[str, str, str]:
        """
        Parse un titre d'annonce.
        Retourne (marque, modele, version)
        
        Gère les cas où le titre commence par le modèle sans marque:
        - "207 1.4 HDi 70ch" -> (Peugeot, 207, 1.4 HDi 70ch)
        """
        if not titre:
            return "", "", ""
        
        titre = titre.strip()
        
        # Marques connues
        marques = [
            "Peugeot", "Renault", "Citroën", "Citroen", "Dacia", "Ford",
            "Volkswagen", "VW", "Toyota", "Opel", "Fiat", "Nissan",
            "Hyundai", "Kia", "Seat", "Skoda", "BMW", "Mercedes", "Audi"
        ]
        
        marque = ""
        modele = ""
        version = titre
        
        # Chercher la marque explicitement mentionnée
        titre_lower = titre.lower()
        for m in marques:
            if m.lower() in titre_lower:
                marque = m
                # Supprimer la marque du reste
                pattern = re.compile(re.escape(m), re.IGNORECASE)
                version = pattern.sub("", version, 1).strip()
                break
        
        # Chercher le modèle (premier mot après marque ou premier mot)
        words = version.split()
        if words:
            # Modèles courants
            modeles_connus = list(self._MODELE_TO_MARQUE.keys())
            
            for word in words[:3]:
                word_clean = re.sub(r"[^a-zA-Z0-9]", "", word)
                for m in modeles_connus:
                    if word_clean.lower() == m.lower():
                        modele = m
                        version = " ".join(w for w in words if w != word)
                        break
                if modele:
                    break
            
            # Si pas trouvé, prendre le premier mot
            if not modele and words:
                modele = words[0]
                version = " ".join(words[1:])
        
        # INFÉRENCE MARQUE: Si modèle connu mais pas de marque, déduire la marque
        if modele and not marque:
            # Chercher dans le mapping
            for modele_ref, marque_ref in self._MODELE_TO_MARQUE.items():
                if modele.lower() == modele_ref.lower():
                    marque = marque_ref
                    break
        
        return (
            self.normalize_marque(marque),
            self.normalize_modele(modele),
            version.strip()
        )
    
    # === Motorisation ===
    
    def extract_motorisation(self, text: str | None) -> str:
        """Extrait la motorisation d'un texte"""
        if not text:
            return ""
        
        # Patterns de motorisation
        patterns = [
            r"(\d+\.\d+)\s*(hdi|dci|tdi|vti|tce|dti|cdti|jtd|d-4d|bluehdi|blue\s*hdi)",
            r"(\d+\.\d+)\s*(l|litres?)?",
            r"(\d{2,3})\s*(ch|cv|hp)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        
        return ""


# Instance globale
_normalize_service: Optional[NormalizeService] = None


def get_normalize_service() -> NormalizeService:
    """Retourne l'instance du service de normalisation"""
    global _normalize_service
    if _normalize_service is None:
        _normalize_service = NormalizeService()
    return _normalize_service
