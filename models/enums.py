"""
Enums - Types énumérés pour le bot
"""

from enum import Enum, auto


class Source(str, Enum):
    """Sources des annonces"""
    LEBONCOIN = "leboncoin"
    AUTOSCOUT24 = "autoscout24"
    LACENTRALE = "lacentrale"
    PARUVENDU = "paruvendu"
    
    def __str__(self) -> str:
        return self.value


class SellerType(str, Enum):
    """Type de vendeur"""
    PARTICULIER = "particulier"
    PROFESSIONNEL = "professionnel"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value


class AlertLevel(str, Enum):
    """Niveau d'alerte basé sur le score"""
    URGENT = "urgent"           # Score >= 80 : affaire exceptionnelle
    INTERESSANT = "interessant" # Score >= 60 : bonne opportunité
    SURVEILLER = "surveiller"   # Score >= 40 : à surveiller
    ARCHIVE = "archive"         # Score < 40 : archivé
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def from_score(cls, score: int) -> "AlertLevel":
        """Détermine le niveau d'alerte à partir du score"""
        if score >= 80:
            return cls.URGENT
        elif score >= 60:
            return cls.INTERESSANT
        elif score >= 40:
            return cls.SURVEILLER
        else:
            return cls.ARCHIVE


class AnnonceStatus(str, Enum):
    """Statut de suivi de l'annonce"""
    NOUVEAU = "nouveau"       # Vient d'être détectée
    CONTACTE = "contacte"     # Vendeur contacté
    EN_COURS = "en_cours"     # Négociation en cours
    ACHETE = "achete"         # Véhicule acheté
    EXPIRE = "expire"         # Annonce expirée/supprimée
    IGNORE = "ignore"         # Ignorée manuellement
    EXCLUE = "exclue"         # Exclue par critères
    
    def __str__(self) -> str:
        return self.value


class Carburant(str, Enum):
    """Type de carburant"""
    DIESEL = "diesel"
    ESSENCE = "essence"
    HYBRIDE = "hybride"
    ELECTRIQUE = "electrique"
    GPL = "gpl"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def from_string(cls, value: str | None) -> "Carburant":
        """Parse une chaîne en Carburant"""
        if not value:
            return cls.UNKNOWN
        
        value_lower = value.lower().strip()
        
        diesel_patterns = ["diesel", "gazole", "hdi", "dci", "tdi", "cdti", "jtd", "d-4d", "dti"]
        essence_patterns = ["essence", "sp95", "sp98", "sans plomb", "vti", "vvt", "tfsi"]
        hybride_patterns = ["hybride", "hybrid"]
        electrique_patterns = ["électrique", "electrique", "ev", "electric"]
        gpl_patterns = ["gpl", "lpg"]
        
        for pattern in diesel_patterns:
            if pattern in value_lower:
                return cls.DIESEL
        
        for pattern in essence_patterns:
            if pattern in value_lower:
                return cls.ESSENCE
        
        for pattern in hybride_patterns:
            if pattern in value_lower:
                return cls.HYBRIDE
        
        for pattern in electrique_patterns:
            if pattern in value_lower:
                return cls.ELECTRIQUE
        
        for pattern in gpl_patterns:
            if pattern in value_lower:
                return cls.GPL
        
        return cls.UNKNOWN


class Boite(str, Enum):
    """Type de boîte de vitesses"""
    MANUELLE = "manuelle"
    AUTOMATIQUE = "automatique"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def from_string(cls, value: str | None) -> "Boite":
        """Parse une chaîne en Boite"""
        if not value:
            return cls.UNKNOWN
        
        value_lower = value.lower().strip()
        
        if any(p in value_lower for p in ["manuel", "manuelle", "mécanique"]):
            return cls.MANUELLE
        
        if any(p in value_lower for p in ["auto", "automatique", "bva", "dsg", "dct"]):
            return cls.AUTOMATIQUE
        
        return cls.UNKNOWN


class Severity(str, Enum):
    """Sévérité des problèmes détectés"""
    CRITICAL = "critical"   # Problème majeur (moteur HS, etc.)
    MAJOR = "major"         # Problème important
    MODERATE = "moderate"   # Problème modéré
    MINOR = "minor"         # Problème mineur
    
    def __str__(self) -> str:
        return self.value
