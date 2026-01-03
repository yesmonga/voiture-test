"""
Annonce Model V2 - Modèle de données robuste
- UUID stable
- Fingerprint pour déduplication
- Timestamps UTC aware
- Score breakdown explicable
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from .enums import Source, SellerType, AlertLevel, AnnonceStatus, Carburant, Boite


def utc_now() -> datetime:
    """Retourne datetime UTC aware"""
    return datetime.now(timezone.utc)


def canonicalize_url(url: str) -> str:
    """
    Normalise une URL pour éviter les doublons dus aux paramètres de tracking.
    Supprime les paramètres UTM, ref, etc.
    """
    if not url:
        return ""
    
    try:
        parsed = urlparse(url)
        
        # Paramètres à supprimer (tracking)
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "ref", "referer", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
            "source", "origin", "searchId", "galleryMode"
        }
        
        # Filtrer les query params
        query_params = parse_qs(parsed.query, keep_blank_values=False)
        clean_params = {
            k: v for k, v in query_params.items() 
            if k.lower() not in tracking_params
        }
        
        # Reconstruire l'URL
        clean_query = urlencode(clean_params, doseq=True) if clean_params else ""
        
        return urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            clean_query,
            ""  # Pas de fragment
        ))
    except Exception:
        return url


@dataclass
class ScoreBreakdown:
    """Détail du calcul de score pour transparence"""
    
    # Composantes principales (sur 100)
    prix_score: int = 0
    prix_detail: str = ""
    
    km_score: int = 0
    km_detail: str = ""
    
    freshness_score: int = 0
    freshness_detail: str = ""
    
    keywords_score: int = 0
    keywords_detail: str = ""
    
    bonus_score: int = 0
    bonus_detail: str = ""
    
    # Pénalités risques
    risk_penalty: int = 0
    risk_detail: str = ""
    
    # Score final
    total: int = 0
    
    # Estimation marge
    margin_min: int = 0
    margin_max: int = 0
    repair_cost_estimate: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoreBreakdown":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ScoreBreakdown":
        return cls.from_dict(json.loads(json_str))
    
    def summary(self) -> str:
        """Résumé lisible du breakdown"""
        parts = []
        if self.prix_score:
            parts.append(f"Prix: {self.prix_score}pts")
        if self.km_score:
            parts.append(f"Km: {self.km_score}pts")
        if self.freshness_score:
            parts.append(f"Fraîcheur: {self.freshness_score}pts")
        if self.keywords_score:
            parts.append(f"Mots-clés: {self.keywords_score}pts")
        if self.bonus_score:
            parts.append(f"Bonus: +{self.bonus_score}pts")
        if self.risk_penalty:
            parts.append(f"Risques: {self.risk_penalty}pts")
        return " | ".join(parts) if parts else "Non calculé"


@dataclass
class Annonce:
    """
    Modèle d'annonce V2 - Production grade
    
    Identifiants:
    - id: UUID interne stable
    - source_listing_id: ID original sur le site source (prioritaire si disponible)
    - url_canonique: URL nettoyée des paramètres tracking
    - fingerprint: Hash pour déduplication multi-sources
    """
    
    # === Identifiants ===
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: Source = Source.AUTOSCOUT24
    source_listing_id: Optional[str] = None
    url: str = ""
    url_canonique: str = ""
    fingerprint: str = ""
    fingerprint_soft: str = ""  # Pour near-duplicate detection
    
    # === Véhicule ===
    marque: str = ""
    modele: str = ""
    version: str = ""
    motorisation: str = ""
    carburant: Carburant = Carburant.UNKNOWN
    boite: Boite = Boite.UNKNOWN
    puissance_ch: Optional[int] = None
    annee: Optional[int] = None
    kilometrage: Optional[int] = None
    prix: Optional[int] = None
    
    # === Localisation ===
    ville: str = ""
    code_postal: str = ""
    departement: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # === Vendeur ===
    seller_type: SellerType = SellerType.UNKNOWN
    seller_name: str = ""
    seller_phone: str = ""
    
    # === Contenu ===
    titre: str = ""
    description: str = ""
    images_urls: list[str] = field(default_factory=list)
    
    # === Dates (UTC aware) ===
    published_at: Optional[datetime] = None
    scraped_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    
    # === Scoring ===
    score_total: int = 0
    score_breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    vehicule_cible_id: str = ""  # ID du véhicule cible matché
    
    # === Mots-clés détectés ===
    keywords_opportunite: list[str] = field(default_factory=list)
    keywords_risque: list[str] = field(default_factory=list)
    
    # === Estimations ===
    margin_estimate_min: int = 0
    margin_estimate_max: int = 0
    repair_cost_estimate: int = 0
    prix_marche_estime: Optional[int] = None
    
    # === Alerte et statut ===
    alert_level: AlertLevel = AlertLevel.ARCHIVE
    status: AnnonceStatus = AnnonceStatus.NOUVEAU
    ignore_reason: str = ""
    
    # === Notifications ===
    notified: bool = False
    notified_at: Optional[datetime] = None
    notify_channels: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Initialisation post-création"""
        # Canonicaliser l'URL
        if self.url and not self.url_canonique:
            self.url_canonique = canonicalize_url(self.url)
        
        # Générer le fingerprint si absent
        if not self.fingerprint:
            self.fingerprint = self._generate_fingerprint()
        
        # Générer le fingerprint_soft pour near-duplicate detection
        if not self.fingerprint_soft:
            self.fingerprint_soft = self._generate_fingerprint_soft()
        
        # Assurer que les dates sont UTC aware
        self._ensure_utc_dates()
    
    def _generate_fingerprint(self) -> str:
        """
        Génère un fingerprint stable pour déduplication.
        Priorité : source_listing_id > combinaison de champs
        """
        if self.source_listing_id:
            # Fingerprint basé sur ID source (le plus fiable)
            data = f"{self.source.value}:{self.source_listing_id}"
        else:
            # Fallback : combinaison de champs normalisés
            data = "|".join([
                self.source.value,
                self._normalize(self.marque),
                self._normalize(self.modele),
                str(self.annee or ""),
                str(self.kilometrage or ""),
                str(self.prix or ""),
                self.departement or "",
                self._normalize(self.titre)[:50]
            ])
        
        return hashlib.sha256(data.encode()).hexdigest()[:32]
    
    def _generate_fingerprint_soft(self) -> str:
        """
        Génère un fingerprint "soft" pour détection near-duplicate.
        
        Moins strict que fingerprint:
        - Ne tient pas compte du prix (peut changer)
        - Ne tient pas compte du km exact (arrondi)
        - Utilise uniquement marque + modèle + année + département
        
        Permet de détecter les annonces republiquées avec modifications mineures.
        """
        km_bucket = ""
        if self.kilometrage:
            # Arrondir aux 50k
            km_bucket = str((self.kilometrage // 50000) * 50000)
        
        data = "|".join([
            self._normalize(self.marque),
            self._normalize(self.modele),
            str(self.annee or ""),
            km_bucket,
            self.departement or "",
        ])
        
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def _normalize(self, text: str) -> str:
        """Normalise un texte pour comparaison"""
        if not text:
            return ""
        # Minuscules, supprime accents et caractères spéciaux
        text = text.lower().strip()
        text = re.sub(r"[éèêë]", "e", text)
        text = re.sub(r"[àâä]", "a", text)
        text = re.sub(r"[ùûü]", "u", text)
        text = re.sub(r"[ôö]", "o", text)
        text = re.sub(r"[îï]", "i", text)
        text = re.sub(r"[ç]", "c", text)
        text = re.sub(r"[^a-z0-9]", "", text)
        return text
    
    def _ensure_utc_dates(self):
        """S'assure que toutes les dates sont UTC aware"""
        for date_field in ["published_at", "scraped_at", "created_at", "updated_at", "notified_at"]:
            value = getattr(self, date_field)
            if value and value.tzinfo is None:
                setattr(self, date_field, value.replace(tzinfo=timezone.utc))
    
    def update_score(self, score: int, breakdown: ScoreBreakdown):
        """Met à jour le score et le breakdown"""
        self.score_total = max(0, min(100, score))
        self.score_breakdown = breakdown
        self.alert_level = AlertLevel.from_score(self.score_total)
        self.margin_estimate_min = breakdown.margin_min
        self.margin_estimate_max = breakdown.margin_max
        self.repair_cost_estimate = breakdown.repair_cost_estimate
        self.updated_at = utc_now()
    
    def mark_notified(self, channels: list[str]):
        """Marque l'annonce comme notifiée"""
        self.notified = True
        self.notified_at = utc_now()
        self.notify_channels = channels
        self.updated_at = utc_now()
    
    def set_status(self, status: AnnonceStatus, reason: str = ""):
        """Change le statut de l'annonce"""
        self.status = status
        if reason:
            self.ignore_reason = reason
        self.updated_at = utc_now()
    
    # === Sérialisation ===
    
    def to_dict(self) -> dict[str, Any]:
        """Sérialise en dictionnaire (pour JSON/DB)"""
        def serialize_value(value: Any) -> Any:
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, (Source, SellerType, AlertLevel, AnnonceStatus, Carburant, Boite)):
                return value.value
            elif isinstance(value, ScoreBreakdown):
                return value.to_dict()
            elif isinstance(value, list):
                return [serialize_value(v) for v in value]
            return value
        
        return {k: serialize_value(v) for k, v in asdict(self).items()}
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Annonce":
        """Désérialise depuis un dictionnaire"""
        # Parser les enums
        if "source" in data and isinstance(data["source"], str):
            data["source"] = Source(data["source"])
        if "seller_type" in data and isinstance(data["seller_type"], str):
            data["seller_type"] = SellerType(data["seller_type"])
        if "alert_level" in data and isinstance(data["alert_level"], str):
            data["alert_level"] = AlertLevel(data["alert_level"])
        if "status" in data and isinstance(data["status"], str):
            data["status"] = AnnonceStatus(data["status"])
        if "carburant" in data and isinstance(data["carburant"], str):
            data["carburant"] = Carburant(data["carburant"])
        if "boite" in data and isinstance(data["boite"], str):
            data["boite"] = Boite(data["boite"])
        
        # Parser les dates
        date_fields = ["published_at", "scraped_at", "created_at", "updated_at", "notified_at"]
        for field_name in date_fields:
            if field_name in data and data[field_name]:
                if isinstance(data[field_name], str):
                    dt = datetime.fromisoformat(data[field_name])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    data[field_name] = dt
        
        # Parser le score breakdown
        if "score_breakdown" in data and isinstance(data["score_breakdown"], dict):
            data["score_breakdown"] = ScoreBreakdown.from_dict(data["score_breakdown"])
        
        # Filtrer les champs valides
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        return cls(**filtered_data)
    
    def to_json(self) -> str:
        """Sérialise en JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "Annonce":
        """Désérialise depuis JSON"""
        return cls.from_dict(json.loads(json_str))
    
    # === Formatage ===
    
    def format_prix(self) -> str:
        """Formate le prix en style français (espaces)"""
        if self.prix is None:
            return "N/C"
        return f"{self.prix:,}".replace(",", " ") + " €"
    
    def format_km(self) -> str:
        """Formate le kilométrage"""
        if self.kilometrage is None:
            return "N/C"
        return f"{self.kilometrage:,}".replace(",", " ") + " km"
    
    def format_notification(self) -> str:
        """Formate pour notification texte"""
        lines = [
            f"🚗 {self.marque} {self.modele} {self.version}".strip(),
            f"💰 {self.format_prix()}",
            f"🛣️ {self.format_km()}",
        ]
        
        if self.annee:
            lines.append(f"📅 {self.annee}")
        
        if self.ville or self.departement:
            loc = self.ville or ""
            if self.departement:
                loc += f" ({self.departement})" if loc else self.departement
            lines.append(f"📍 {loc}")
        
        lines.append(f"📊 Score: {self.score_total}/100 ({self.alert_level.value})")
        
        if self.margin_estimate_min or self.margin_estimate_max:
            lines.append(f"💵 Marge: {self.margin_estimate_min:,} - {self.margin_estimate_max:,} €".replace(",", " "))
        
        if self.keywords_opportunite:
            lines.append(f"✅ {', '.join(self.keywords_opportunite[:3])}")
        
        if self.keywords_risque:
            lines.append(f"⚠️ {', '.join(self.keywords_risque[:3])}")
        
        lines.append(f"🔗 {self.url}")
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        return f"<Annonce {self.marque} {self.modele} {self.format_prix()} - Score {self.score_total}>"
