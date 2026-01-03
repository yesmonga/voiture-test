"""
Database - Gestion de la base de données SQLite
"""

import os
import json
from datetime import datetime
from typing import Optional, List
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL
from .annonce import Annonce

Base = declarative_base()


class AnnonceDB(Base):
    """Modèle SQLAlchemy pour les annonces"""
    __tablename__ = "annonces"
    
    id = Column(String(32), primary_key=True)
    source = Column(String(50), nullable=False, index=True)
    url = Column(String(500), unique=True, nullable=False)
    
    # Infos véhicule
    marque = Column(String(50))
    modele = Column(String(100))
    version = Column(String(100))
    motorisation = Column(String(100))
    carburant = Column(String(20))
    annee = Column(Integer)
    kilometrage = Column(Integer)
    prix = Column(Integer, index=True)
    
    # Localisation
    ville = Column(String(100))
    code_postal = Column(String(10))
    departement = Column(String(5), index=True)
    
    # Contact
    telephone = Column(String(20))
    nom_vendeur = Column(String(100))
    type_vendeur = Column(String(20), default="particulier")
    
    # Contenu
    titre = Column(String(500))
    description = Column(Text)
    images_urls = Column(Text)  # JSON
    
    # Scoring
    score_rentabilite = Column(Integer, default=0, index=True)
    mots_cles_detectes = Column(Text)  # JSON
    vehicule_cible_id = Column(String(50))
    marge_estimee_min = Column(Integer)
    marge_estimee_max = Column(Integer)
    
    # Métadonnées
    date_publication = Column(DateTime)
    date_scraping = Column(DateTime, default=datetime.now)
    notifie = Column(Boolean, default=False)
    statut = Column(String(20), default="nouveau")
    notes = Column(Text)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Index composites pour les requêtes fréquentes
    __table_args__ = (
        Index('idx_score_date', 'score_rentabilite', 'date_publication'),
        Index('idx_source_dept', 'source', 'departement'),
    )


class Database:
    """Gestionnaire de base de données"""
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or DATABASE_URL
        
        # Créer le répertoire data si nécessaire
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "")
            os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        
        self.engine = create_engine(
            self.database_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in self.database_url else {}
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # Créer les tables
        Base.metadata.create_all(self.engine)
    
    @contextmanager
    def get_session(self) -> Session:
        """Context manager pour les sessions"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def _annonce_to_db(self, annonce: Annonce) -> AnnonceDB:
        """Convertit une Annonce en AnnonceDB"""
        return AnnonceDB(
            id=annonce.id,
            source=annonce.source,
            url=annonce.url,
            marque=annonce.marque,
            modele=annonce.modele,
            version=annonce.version,
            motorisation=annonce.motorisation,
            carburant=annonce.carburant,
            annee=annonce.annee,
            kilometrage=annonce.kilometrage,
            prix=annonce.prix,
            ville=annonce.ville,
            code_postal=annonce.code_postal,
            departement=annonce.departement,
            telephone=annonce.telephone,
            nom_vendeur=annonce.nom_vendeur,
            type_vendeur=annonce.type_vendeur,
            titre=annonce.titre,
            description=annonce.description,
            images_urls=json.dumps(annonce.images_urls),
            score_rentabilite=annonce.score_rentabilite,
            mots_cles_detectes=json.dumps(annonce.mots_cles_detectes),
            vehicule_cible_id=annonce.vehicule_cible_id,
            marge_estimee_min=annonce.marge_estimee_min,
            marge_estimee_max=annonce.marge_estimee_max,
            date_publication=annonce.date_publication,
            date_scraping=annonce.date_scraping,
            notifie=annonce.notifie,
            statut=annonce.statut,
            notes=annonce.notes,
            created_at=annonce.created_at,
            updated_at=annonce.updated_at
        )
    
    def _db_to_annonce(self, db_annonce: AnnonceDB) -> Annonce:
        """Convertit une AnnonceDB en Annonce"""
        return Annonce(
            url=db_annonce.url,
            source=db_annonce.source,
            marque=db_annonce.marque,
            modele=db_annonce.modele,
            version=db_annonce.version,
            motorisation=db_annonce.motorisation,
            carburant=db_annonce.carburant,
            annee=db_annonce.annee,
            kilometrage=db_annonce.kilometrage,
            prix=db_annonce.prix,
            ville=db_annonce.ville,
            code_postal=db_annonce.code_postal,
            departement=db_annonce.departement,
            telephone=db_annonce.telephone,
            nom_vendeur=db_annonce.nom_vendeur,
            type_vendeur=db_annonce.type_vendeur,
            titre=db_annonce.titre,
            description=db_annonce.description,
            images_urls=json.loads(db_annonce.images_urls) if db_annonce.images_urls else [],
            score_rentabilite=db_annonce.score_rentabilite,
            mots_cles_detectes=json.loads(db_annonce.mots_cles_detectes) if db_annonce.mots_cles_detectes else [],
            vehicule_cible_id=db_annonce.vehicule_cible_id,
            marge_estimee_min=db_annonce.marge_estimee_min,
            marge_estimee_max=db_annonce.marge_estimee_max,
            date_publication=db_annonce.date_publication,
            date_scraping=db_annonce.date_scraping,
            notifie=db_annonce.notifie,
            statut=db_annonce.statut,
            notes=db_annonce.notes,
            created_at=db_annonce.created_at,
            updated_at=db_annonce.updated_at
        )
    
    def save_annonce(self, annonce: Annonce) -> bool:
        """Sauvegarde une annonce (insert ou update)"""
        with self.get_session() as session:
            existing = session.query(AnnonceDB).filter_by(id=annonce.id).first()
            
            if existing:
                # Update
                for key, value in self._annonce_to_db(annonce).__dict__.items():
                    if not key.startswith('_'):
                        setattr(existing, key, value)
                existing.updated_at = datetime.now()
                return False  # Pas nouveau
            else:
                # Insert
                db_annonce = self._annonce_to_db(annonce)
                session.add(db_annonce)
                return True  # Nouveau
    
    def get_annonce(self, annonce_id: str) -> Optional[Annonce]:
        """Récupère une annonce par ID"""
        with self.get_session() as session:
            db_annonce = session.query(AnnonceDB).filter_by(id=annonce_id).first()
            return self._db_to_annonce(db_annonce) if db_annonce else None
    
    def get_annonce_by_url(self, url: str) -> Optional[Annonce]:
        """Récupère une annonce par URL"""
        with self.get_session() as session:
            db_annonce = session.query(AnnonceDB).filter_by(url=url).first()
            return self._db_to_annonce(db_annonce) if db_annonce else None
    
    def exists(self, url: str) -> bool:
        """Vérifie si une annonce existe déjà"""
        with self.get_session() as session:
            return session.query(AnnonceDB).filter_by(url=url).count() > 0
    
    def get_annonces(
        self,
        source: str = None,
        departement: str = None,
        score_min: int = None,
        statut: str = None,
        notifie: bool = None,
        limit: int = 100,
        order_by_score: bool = True
    ) -> List[Annonce]:
        """Récupère des annonces avec filtres"""
        with self.get_session() as session:
            query = session.query(AnnonceDB)
            
            if source:
                query = query.filter(AnnonceDB.source == source)
            if departement:
                query = query.filter(AnnonceDB.departement == departement)
            if score_min is not None:
                query = query.filter(AnnonceDB.score_rentabilite >= score_min)
            if statut:
                query = query.filter(AnnonceDB.statut == statut)
            if notifie is not None:
                query = query.filter(AnnonceDB.notifie == notifie)
            
            if order_by_score:
                query = query.order_by(AnnonceDB.score_rentabilite.desc())
            else:
                query = query.order_by(AnnonceDB.date_scraping.desc())
            
            query = query.limit(limit)
            
            return [self._db_to_annonce(a) for a in query.all()]
    
    def get_non_notifiees(self, score_min: int = 40) -> List[Annonce]:
        """Récupère les annonces non notifiées avec un score minimum"""
        with self.get_session() as session:
            query = session.query(AnnonceDB).filter(
                AnnonceDB.notifie == False,
                AnnonceDB.score_rentabilite >= score_min
            ).order_by(AnnonceDB.score_rentabilite.desc())
            
            return [self._db_to_annonce(a) for a in query.all()]
    
    def mark_notified(self, annonce_id: str) -> None:
        """Marque une annonce comme notifiée"""
        with self.get_session() as session:
            annonce = session.query(AnnonceDB).filter_by(id=annonce_id).first()
            if annonce:
                annonce.notifie = True
                annonce.updated_at = datetime.now()
    
    def update_statut(self, annonce_id: str, statut: str, notes: str = None) -> None:
        """Met à jour le statut d'une annonce"""
        with self.get_session() as session:
            annonce = session.query(AnnonceDB).filter_by(id=annonce_id).first()
            if annonce:
                annonce.statut = statut
                if notes:
                    annonce.notes = notes
                annonce.updated_at = datetime.now()
    
    def get_stats(self) -> dict:
        """Retourne des statistiques sur les annonces"""
        with self.get_session() as session:
            total = session.query(AnnonceDB).count()
            par_source = {}
            par_statut = {}
            par_score = {"urgent": 0, "interessant": 0, "surveiller": 0, "archive": 0}
            
            for source in ["leboncoin", "lacentrale", "paruvendu", "autoscout24"]:
                par_source[source] = session.query(AnnonceDB).filter_by(source=source).count()
            
            for statut in ["nouveau", "contacté", "acheté", "expiré", "ignoré"]:
                par_statut[statut] = session.query(AnnonceDB).filter_by(statut=statut).count()
            
            par_score["urgent"] = session.query(AnnonceDB).filter(AnnonceDB.score_rentabilite >= 80).count()
            par_score["interessant"] = session.query(AnnonceDB).filter(
                AnnonceDB.score_rentabilite >= 60,
                AnnonceDB.score_rentabilite < 80
            ).count()
            par_score["surveiller"] = session.query(AnnonceDB).filter(
                AnnonceDB.score_rentabilite >= 40,
                AnnonceDB.score_rentabilite < 60
            ).count()
            par_score["archive"] = session.query(AnnonceDB).filter(AnnonceDB.score_rentabilite < 40).count()
            
            return {
                "total": total,
                "par_source": par_source,
                "par_statut": par_statut,
                "par_score": par_score
            }


# Instance globale
_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Retourne l'instance de la base de données"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
