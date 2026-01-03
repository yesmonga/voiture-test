"""
Repository - Data Access Object pour SQLite
Gestion propre des opérations CRUD sur les annonces
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from models.annonce_v2 import Annonce, ScoreBreakdown
from models.enums import Source, SellerType, AlertLevel, AnnonceStatus, Carburant, Boite
from config.settings import get_settings, DATA_DIR

# Chemin du schéma SQL
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def utc_now_iso() -> str:
    """Retourne datetime UTC au format ISO"""
    return datetime.now(timezone.utc).isoformat()


class AnnonceRepository:
    """Repository pour les annonces"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(DATA_DIR / "annonces.db")
        
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialise la base de données avec le schéma"""
        with self._get_connection() as conn:
            if SCHEMA_PATH.exists():
                conn.executescript(SCHEMA_PATH.read_text())
            conn.commit()
    
    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager pour les connexions"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _row_to_annonce(self, row: sqlite3.Row) -> Annonce:
        """Convertit une ligne DB en Annonce"""
        data = dict(row)
        
        # Parser les champs JSON
        json_fields = ["images_urls", "keywords_opportunite", "keywords_risque", "notify_channels"]
        for field in json_fields:
            if data.get(field):
                try:
                    data[field] = json.loads(data[field])
                except (json.JSONDecodeError, TypeError):
                    data[field] = []
        
        # Parser score_breakdown
        if data.get("score_breakdown"):
            try:
                data["score_breakdown"] = ScoreBreakdown.from_json(data["score_breakdown"])
            except (json.JSONDecodeError, TypeError):
                data["score_breakdown"] = ScoreBreakdown()
        
        # Parser les enums
        if data.get("source"):
            data["source"] = Source(data["source"])
        if data.get("seller_type"):
            data["seller_type"] = SellerType(data["seller_type"])
        if data.get("alert_level"):
            data["alert_level"] = AlertLevel(data["alert_level"])
        if data.get("status"):
            data["status"] = AnnonceStatus(data["status"])
        if data.get("carburant"):
            data["carburant"] = Carburant(data["carburant"])
        if data.get("boite"):
            data["boite"] = Boite(data["boite"])
        
        # Parser les dates
        date_fields = ["published_at", "scraped_at", "created_at", "updated_at", "notified_at"]
        for field in date_fields:
            if data.get(field):
                try:
                    dt = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
                    data[field] = dt
                except (ValueError, AttributeError):
                    data[field] = None
        
        # Convertir notified
        data["notified"] = bool(data.get("notified", 0))
        
        return Annonce.from_dict(data)
    
    def _annonce_to_row(self, annonce: Annonce) -> dict[str, Any]:
        """Convertit une Annonce en données pour DB"""
        data = annonce.to_dict()
        
        # Sérialiser les listes en JSON
        json_fields = ["images_urls", "keywords_opportunite", "keywords_risque", "notify_channels"]
        for field in json_fields:
            if field in data and isinstance(data[field], list):
                data[field] = json.dumps(data[field], ensure_ascii=False)
        
        # Sérialiser score_breakdown
        if "score_breakdown" in data and isinstance(data["score_breakdown"], dict):
            data["score_breakdown"] = json.dumps(data["score_breakdown"], ensure_ascii=False)
        
        # Convertir notified en int
        data["notified"] = 1 if data.get("notified") else 0
        
        return data
    
    # === CRUD Operations ===
    
    def save(self, annonce: Annonce) -> bool:
        """
        Sauvegarde ou met à jour une annonce.
        Upsert sur fingerprint (clé de déduplication) au lieu de id.
        """
        annonce.updated_at = datetime.now(timezone.utc)
        data = self._annonce_to_row(annonce)
        
        columns = list(data.keys())
        placeholders = ["?" for _ in columns]
        # Exclure id et fingerprint de l'update (on garde l'original)
        updates = [f"{col} = excluded.{col}" for col in columns 
                   if col not in ("id", "fingerprint", "created_at")]
        
        # Upsert sur fingerprint (unique) - résout le bug UNIQUE constraint
        sql = f"""
            INSERT INTO annonces ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT(fingerprint) DO UPDATE SET {', '.join(updates)}
        """
        
        try:
            with self._get_connection() as conn:
                conn.execute(sql, [data[col] for col in columns])
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erreur save: {e}")
            return False
    
    def get_by_id(self, annonce_id: str) -> Optional[Annonce]:
        """Récupère une annonce par son ID"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM annonces WHERE id = ?", 
                (annonce_id,)
            ).fetchone()
            
            if row:
                return self._row_to_annonce(row)
        return None
    
    def get_by_fingerprint(self, fingerprint: str) -> Optional[Annonce]:
        """Récupère une annonce par son fingerprint"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM annonces WHERE fingerprint = ?",
                (fingerprint,)
            ).fetchone()
            
            if row:
                return self._row_to_annonce(row)
        return None
    
    def get_by_url(self, url: str) -> Optional[Annonce]:
        """Récupère une annonce par son URL (canonique ou originale)"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM annonces WHERE url = ? OR url_canonique = ?",
                (url, url)
            ).fetchone()
            
            if row:
                return self._row_to_annonce(row)
        return None
    
    def exists(self, fingerprint: str = None, url: str = None) -> bool:
        """Vérifie si une annonce existe déjà"""
        with self._get_connection() as conn:
            if fingerprint:
                row = conn.execute(
                    "SELECT 1 FROM annonces WHERE fingerprint = ?",
                    (fingerprint,)
                ).fetchone()
                if row:
                    return True
            
            if url:
                row = conn.execute(
                    "SELECT 1 FROM annonces WHERE url = ? OR url_canonique = ?",
                    (url, url)
                ).fetchone()
                if row:
                    return True
        
        return False
    
    def get_by_source_listing(self, source: Source, source_listing_id: str) -> Optional[Annonce]:
        """Récupère une annonce par (source, source_listing_id)"""
        if not source_listing_id:
            return None
        
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM annonces WHERE source = ? AND source_listing_id = ?",
                (source.value, source_listing_id)
            ).fetchone()
            
            if row:
                return self._row_to_annonce(row)
        return None
    
    def find_near_duplicates(self, fingerprint_soft: str) -> list[Annonce]:
        """
        Trouve les annonces avec le même fingerprint_soft.
        Utilisé pour la détection de near-duplicates.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM annonces WHERE fingerprint_soft = ? ORDER BY created_at DESC",
                (fingerprint_soft,)
            ).fetchall()
            
            return [self._row_to_annonce(row) for row in rows]
    
    def is_near_duplicate(self, annonce: Annonce) -> tuple[bool, Optional[Annonce]]:
        """
        Vérifie si une annonce est un near-duplicate d'une existante.
        
        Returns:
            (is_duplicate, existing_annonce)
        """
        if not annonce.fingerprint_soft:
            return False, None
        
        near_dupes = self.find_near_duplicates(annonce.fingerprint_soft)
        
        # Exclure l'annonce elle-même
        near_dupes = [a for a in near_dupes if a.id != annonce.id]
        
        if near_dupes:
            return True, near_dupes[0]
        
        return False, None
    
    def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        source: Optional[Source] = None,
        status: Optional[AnnonceStatus] = None,
        alert_level: Optional[AlertLevel] = None,
        min_score: Optional[int] = None,
        not_notified: bool = False,
        order_by: str = "score_total DESC"
    ) -> list[Annonce]:
        """Récupère des annonces avec filtres"""
        conditions = []
        params = []
        
        if source:
            conditions.append("source = ?")
            params.append(source.value)
        
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        
        if alert_level:
            conditions.append("alert_level = ?")
            params.append(alert_level.value)
        
        if min_score is not None:
            conditions.append("score_total >= ?")
            params.append(min_score)
        
        if not_notified:
            conditions.append("notified = 0")
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        # Valider order_by pour éviter injection SQL
        valid_orders = ["score_total DESC", "score_total ASC", "created_at DESC", 
                       "created_at ASC", "prix ASC", "prix DESC"]
        if order_by not in valid_orders:
            order_by = "score_total DESC"
        
        sql = f"""
            SELECT * FROM annonces
            {where_clause}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        annonces = []
        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            for row in rows:
                annonces.append(self._row_to_annonce(row))
        
        return annonces
    
    def mark_notified(self, annonce_id: str, channels: list[str]) -> bool:
        """Marque une annonce comme notifiée"""
        sql = """
            UPDATE annonces
            SET notified = 1, notified_at = ?, notify_channels = ?, updated_at = ?
            WHERE id = ?
        """
        now = utc_now_iso()
        channels_json = json.dumps(channels, ensure_ascii=False)
        
        try:
            with self._get_connection() as conn:
                conn.execute(sql, (now, channels_json, now, annonce_id))
                conn.commit()
            return True
        except sqlite3.Error:
            return False
    
    def update_status(self, annonce_id: str, status: AnnonceStatus, reason: str = "") -> bool:
        """Met à jour le statut d'une annonce"""
        sql = """
            UPDATE annonces
            SET status = ?, ignore_reason = ?, updated_at = ?
            WHERE id = ?
        """
        try:
            with self._get_connection() as conn:
                conn.execute(sql, (status.value, reason, utc_now_iso(), annonce_id))
                conn.commit()
            return True
        except sqlite3.Error:
            return False
    
    def delete(self, annonce_id: str) -> bool:
        """Supprime une annonce"""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM annonces WHERE id = ?", (annonce_id,))
                conn.commit()
            return True
        except sqlite3.Error:
            return False
    
    # === Statistiques ===
    
    def get_stats(self) -> dict[str, Any]:
        """Retourne les statistiques globales"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM v_stats").fetchone()
            if row:
                return dict(row)
        return {}
    
    def get_stats_by_source(self) -> list[dict[str, Any]]:
        """Retourne les statistiques par source"""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM v_stats_par_source").fetchall()
            return [dict(row) for row in rows]
    
    def count(
        self,
        source: Optional[Source] = None,
        status: Optional[AnnonceStatus] = None
    ) -> int:
        """Compte les annonces avec filtres"""
        conditions = []
        params = []
        
        if source:
            conditions.append("source = ?")
            params.append(source.value)
        
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as count FROM annonces {where_clause}",
                params
            ).fetchone()
            return row["count"] if row else 0
    
    # === Scan History ===
    
    def log_scan(
        self,
        source: str,
        index_count: int = 0,
        new_count: int = 0,
        notified_count: int = 0,
        error_count: int = 0
    ):
        """Log simplifié d'un scan (insert direct)"""
        sql = """
            INSERT INTO scan_history (source, started_at, finished_at, status, 
                                      listings_found, listings_new, errors_count)
            VALUES (?, ?, ?, 'completed', ?, ?, ?)
        """
        now = utc_now_iso()
        try:
            with self._get_connection() as conn:
                conn.execute(sql, (source, now, now, index_count, new_count, error_count))
                conn.commit()
        except Exception as e:
            print(f"⚠️ log_scan error: {e}")
    
    def log_scan_start(self, source: Source) -> int:
        """Enregistre le début d'un scan"""
        sql = """
            INSERT INTO scan_history (source, started_at, status)
            VALUES (?, ?, 'running')
        """
        with self._get_connection() as conn:
            cursor = conn.execute(sql, (source.value, utc_now_iso()))
            conn.commit()
            return cursor.lastrowid
    
    def log_scan_end(
        self,
        scan_id: int,
        status: str,
        listings_found: int = 0,
        listings_new: int = 0,
        errors_count: int = 0,
        error_message: str = ""
    ):
        """Enregistre la fin d'un scan"""
        sql = """
            UPDATE scan_history
            SET finished_at = ?, status = ?, 
                listings_found = ?, listings_new = ?, 
                errors_count = ?, error_message = ?,
                duration_seconds = (julianday(?) - julianday(started_at)) * 86400
            WHERE id = ?
        """
        now = utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(sql, (
                now, status, listings_found, listings_new,
                errors_count, error_message, now, scan_id
            ))
            conn.commit()


# Instance globale (singleton)
_repo: Optional[AnnonceRepository] = None


def get_repo() -> AnnonceRepository:
    """Retourne l'instance du repository"""
    global _repo
    if _repo is None:
        _repo = AnnonceRepository()
    return _repo
