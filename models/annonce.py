"""
Modèle Annonce - Représentation d'une annonce de véhicule
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import json
import hashlib


@dataclass
class Annonce:
    """Représentation d'une annonce de véhicule d'occasion"""
    
    # Identifiants
    url: str
    source: str  # leboncoin, lacentrale, paruvendu, autoscout24
    
    # Informations véhicule
    marque: Optional[str] = None
    modele: Optional[str] = None
    version: Optional[str] = None
    motorisation: Optional[str] = None
    carburant: Optional[str] = None
    annee: Optional[int] = None
    kilometrage: Optional[int] = None
    prix: Optional[int] = None
    
    # Localisation
    ville: Optional[str] = None
    code_postal: Optional[str] = None
    departement: Optional[str] = None
    
    # Contact
    telephone: Optional[str] = None
    nom_vendeur: Optional[str] = None
    type_vendeur: str = "particulier"  # particulier ou pro
    
    # Contenu
    titre: Optional[str] = None
    description: Optional[str] = None
    images_urls: List[str] = field(default_factory=list)
    
    # Scoring
    score_rentabilite: int = 0
    mots_cles_detectes: List[str] = field(default_factory=list)
    vehicule_cible_id: Optional[str] = None  # ex: "peugeot_207_hdi"
    marge_estimee_min: Optional[int] = None
    marge_estimee_max: Optional[int] = None
    
    # Métadonnées
    date_publication: Optional[datetime] = None
    date_scraping: datetime = field(default_factory=datetime.now)
    notifie: bool = False
    statut: str = "nouveau"  # nouveau, contacté, acheté, expiré, ignoré
    notes: Optional[str] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    @property
    def id(self) -> str:
        """Génère un ID unique basé sur l'URL"""
        return hashlib.md5(self.url.encode()).hexdigest()
    
    @property
    def images_urls_json(self) -> str:
        """Retourne les URLs d'images en JSON"""
        return json.dumps(self.images_urls)
    
    @property
    def mots_cles_detectes_json(self) -> str:
        """Retourne les mots-clés détectés en JSON"""
        return json.dumps(self.mots_cles_detectes)
    
    @property
    def niveau_alerte(self) -> str:
        """Détermine le niveau d'alerte basé sur le score"""
        if self.score_rentabilite >= 80:
            return "urgent"
        elif self.score_rentabilite >= 60:
            return "interessant"
        elif self.score_rentabilite >= 40:
            return "surveiller"
        return "archive"
    
    @property
    def emoji_alerte(self) -> str:
        """Emoji correspondant au niveau d'alerte"""
        mapping = {
            "urgent": "🔴",
            "interessant": "🟠",
            "surveiller": "🟡",
            "archive": "⚪"
        }
        return mapping.get(self.niveau_alerte, "⚪")
    
    @property
    def age_minutes(self) -> int:
        """Âge de l'annonce en minutes depuis la publication"""
        if not self.date_publication:
            return 999999
        delta = datetime.now() - self.date_publication
        return int(delta.total_seconds() / 60)
    
    def to_dict(self) -> dict:
        """Convertit l'annonce en dictionnaire"""
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source,
            "marque": self.marque,
            "modele": self.modele,
            "version": self.version,
            "motorisation": self.motorisation,
            "carburant": self.carburant,
            "annee": self.annee,
            "kilometrage": self.kilometrage,
            "prix": self.prix,
            "ville": self.ville,
            "code_postal": self.code_postal,
            "departement": self.departement,
            "telephone": self.telephone,
            "nom_vendeur": self.nom_vendeur,
            "type_vendeur": self.type_vendeur,
            "titre": self.titre,
            "description": self.description,
            "images_urls": self.images_urls,
            "score_rentabilite": self.score_rentabilite,
            "mots_cles_detectes": self.mots_cles_detectes,
            "vehicule_cible_id": self.vehicule_cible_id,
            "marge_estimee_min": self.marge_estimee_min,
            "marge_estimee_max": self.marge_estimee_max,
            "date_publication": self.date_publication.isoformat() if self.date_publication else None,
            "date_scraping": self.date_scraping.isoformat() if self.date_scraping else None,
            "notifie": self.notifie,
            "statut": self.statut,
            "notes": self.notes,
            "niveau_alerte": self.niveau_alerte,
            "age_minutes": self.age_minutes
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Annonce":
        """Crée une annonce depuis un dictionnaire"""
        # Gérer les champs datetime
        if data.get("date_publication") and isinstance(data["date_publication"], str):
            data["date_publication"] = datetime.fromisoformat(data["date_publication"])
        if data.get("date_scraping") and isinstance(data["date_scraping"], str):
            data["date_scraping"] = datetime.fromisoformat(data["date_scraping"])
        if data.get("created_at") and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at") and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        
        # Gérer les champs JSON
        if data.get("images_urls") and isinstance(data["images_urls"], str):
            data["images_urls"] = json.loads(data["images_urls"])
        if data.get("mots_cles_detectes") and isinstance(data["mots_cles_detectes"], str):
            data["mots_cles_detectes"] = json.loads(data["mots_cles_detectes"])
        
        # Retirer les champs calculés
        data.pop("id", None)
        data.pop("niveau_alerte", None)
        data.pop("age_minutes", None)
        
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def format_notification(self) -> str:
        """Formate l'annonce pour une notification"""
        lines = [
            f"🚗 ALERTE VÉHICULE - Score: {self.score_rentabilite}/100 {self.emoji_alerte}",
            "",
            f"📌 {self.marque} {self.modele} {self.version or ''}".strip(),
            f"💰 Prix: {self.prix:,}€" if self.prix else "💰 Prix: Non indiqué",
            f"📍 Lieu: {self.ville} ({self.departement})" if self.ville else "",
            f"🛣️ Km: {self.kilometrage:,} km" if self.kilometrage else "",
            f"📅 Année: {self.annee}" if self.annee else "",
            f"⏱️ Publié il y a: {self.age_minutes} min" if self.age_minutes < 999999 else "",
        ]
        
        if self.mots_cles_detectes:
            lines.append(f"\n🔑 Mots-clés: {', '.join(self.mots_cles_detectes[:5])}")
        
        if self.telephone:
            lines.append(f"\n📞 Contact: {self.telephone}")
        
        lines.append(f"\n🔗 {self.url}")
        
        if self.marge_estimee_min and self.marge_estimee_max:
            lines.append(f"\n💵 Marge potentielle: {self.marge_estimee_min}€ - {self.marge_estimee_max}€")
        
        return "\n".join(line for line in lines if line is not None)
    
    def __str__(self) -> str:
        return f"<Annonce {self.marque} {self.modele} {self.prix}€ - {self.source}>"
    
    def __repr__(self) -> str:
        return self.__str__()
