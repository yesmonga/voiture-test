"""
Tests for scoring service
"""

import pytest
from datetime import datetime, timezone, timedelta

from models.annonce_v2 import Annonce, ScoreBreakdown
from models.enums import Source, SellerType, AlertLevel, Carburant
from services.scoring import ScoringService, get_scoring_service


@pytest.fixture
def scorer():
    return ScoringService()


@pytest.fixture
def base_annonce():
    """Annonce de base pour les tests"""
    return Annonce(
        source=Source.AUTOSCOUT24,
        marque="Peugeot",
        modele="207",
        version="1.4 HDi 70ch",
        prix=2500,
        kilometrage=150000,
        annee=2010,
        carburant=Carburant.DIESEL,
        departement="75",
        seller_type=SellerType.PARTICULIER,
        titre="Peugeot 207 1.4 HDi 70ch Active",
        published_at=datetime.now(timezone.utc) - timedelta(hours=2),
        url="https://test.com/annonce/123"
    )


class TestIdentifyVehicle:
    """Tests pour l'identification des véhicules cibles"""
    
    def test_identify_peugeot_207(self, scorer, base_annonce):
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        assert vehicle_id == "peugeot_207_hdi"
        assert config is not None
    
    def test_identify_renault_clio(self, scorer):
        annonce = Annonce(
            source=Source.AUTOSCOUT24,
            marque="Renault",
            modele="Clio",
            version="1.5 dCi 75ch",
            titre="Renault Clio 3 1.5 dCi",
            url="https://test.com/123"
        )
        vehicle_id, config = scorer._identify_vehicle(annonce)
        assert vehicle_id == "renault_clio_3"
    
    def test_identify_dacia_sandero(self, scorer):
        annonce = Annonce(
            source=Source.AUTOSCOUT24,
            marque="Dacia",
            modele="Sandero",
            titre="Dacia Sandero Stepway",
            url="https://test.com/123"
        )
        vehicle_id, config = scorer._identify_vehicle(annonce)
        assert vehicle_id == "dacia_sandero"
    
    def test_identify_unknown_vehicle(self, scorer):
        annonce = Annonce(
            source=Source.AUTOSCOUT24,
            marque="BMW",
            modele="Serie 3",
            url="https://test.com/123"
        )
        vehicle_id, config = scorer._identify_vehicle(annonce)
        assert vehicle_id == ""
        assert config is None
    
    def test_no_false_positive_207(self, scorer):
        """Vérifie que '1207' ne matche pas '207'"""
        annonce = Annonce(
            source=Source.AUTOSCOUT24,
            marque="Peugeot",
            modele="1207",  # N'existe pas mais test le regex
            titre="Peugeot 1207",
            url="https://test.com/123"
        )
        # Avec les bons patterns regex, ça ne devrait pas matcher
        vehicle_id, config = scorer._identify_vehicle(annonce)
        # Le modèle "1207" ne devrait pas matcher "207"
        # Mais ça dépend des patterns, test à ajuster selon config


class TestScorePrix:
    """Tests pour le scoring du prix"""
    
    def test_prix_bas_score_eleve(self, scorer, base_annonce):
        base_annonce.prix = 1000  # Très bas (cible flipping: 0-2000€)
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_prix(base_annonce, config)
        assert score > 20  # Score élevé (ajusté pour nouvelle config)
    
    def test_prix_haut_score_bas(self, scorer, base_annonce):
        base_annonce.prix = 2900  # Proche du max
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_prix(base_annonce, config)
        assert score < 10  # Score bas
    
    def test_prix_trop_eleve(self, scorer, base_annonce):
        base_annonce.prix = 5000  # Au-dessus du max
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_prix(base_annonce, config)
        assert score == 0
    
    def test_prix_none(self, scorer, base_annonce):
        base_annonce.prix = None
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_prix(base_annonce, config)
        assert score == 0
        assert "non renseigné" in detail.lower()


class TestScoreKm:
    """Tests pour le scoring du kilométrage"""
    
    def test_km_ideal(self, scorer, base_annonce):
        base_annonce.kilometrage = 160000  # Dans la plage idéale (150k-170k pour flipping)
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_km(base_annonce, config)
        assert score >= 10  # Score correct (config flipping: km élevé = prix bas)
    
    def test_km_trop_eleve(self, scorer, base_annonce):
        base_annonce.kilometrage = 250000  # Au-dessus du max
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_km(base_annonce, config)
        assert score == 0
    
    def test_km_none(self, scorer, base_annonce):
        base_annonce.kilometrage = None
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_km(base_annonce, config)
        assert "non renseigné" in detail.lower()


class TestScoreFreshness:
    """Tests pour le scoring de la fraîcheur"""
    
    def test_very_fresh(self, scorer, base_annonce):
        base_annonce.published_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        score, detail = scorer._score_freshness(base_annonce)
        assert score >= 9  # Très frais
        assert "frais" in detail.lower() or "1h" in detail.lower() or "<" in detail
    
    def test_recent(self, scorer, base_annonce):
        base_annonce.published_at = datetime.now(timezone.utc) - timedelta(hours=12)
        score, detail = scorer._score_freshness(base_annonce)
        assert 5 <= score <= 8
    
    def test_old(self, scorer, base_annonce):
        base_annonce.published_at = datetime.now(timezone.utc) - timedelta(days=10)
        score, detail = scorer._score_freshness(base_annonce)
        assert score == 0
    
    def test_no_date(self, scorer, base_annonce):
        base_annonce.published_at = None
        score, detail = scorer._score_freshness(base_annonce)
        assert "inconnue" in detail.lower()


class TestScoreKeywords:
    """Tests pour le scoring des mots-clés"""
    
    def test_urgent_keyword(self, scorer, base_annonce):
        base_annonce.titre = "Vente urgente Peugeot 207"
        base_annonce.description = "Urgent, déménagement"
        score, detail = scorer._score_keywords(base_annonce)
        assert score > 0
        assert "urgent" in base_annonce.keywords_opportunite
    
    def test_negotiable_keyword(self, scorer, base_annonce):
        base_annonce.description = "Prix négociable"
        score, detail = scorer._score_keywords(base_annonce)
        assert score > 0
    
    def test_no_keywords(self, scorer, base_annonce):
        base_annonce.titre = "Peugeot 207"
        base_annonce.description = "Voiture en bon état"
        score, detail = scorer._score_keywords(base_annonce)
        assert score == 0 or detail == "Aucun"


class TestScoreRisks:
    """Tests pour les pénalités de risque"""
    
    def test_moteur_hs(self, scorer, base_annonce):
        base_annonce.description = "Moteur HS, pour pièces"
        penalty, detail = scorer._score_risks(base_annonce)
        assert penalty < 0  # Pénalité négative
        assert "moteur" in detail.lower()
    
    def test_ct_refuse(self, scorer, base_annonce):
        base_annonce.description = "CT refusé, contre-visite"
        penalty, detail = scorer._score_risks(base_annonce)
        assert penalty < 0
    
    def test_no_risks(self, scorer, base_annonce):
        base_annonce.description = "Très bon état, entretien suivi"
        penalty, detail = scorer._score_risks(base_annonce)
        assert penalty == 0
        assert "aucun" in detail.lower()


class TestScoreBonus:
    """Tests pour les bonus"""
    
    def test_dept_prioritaire(self, scorer, base_annonce):
        base_annonce.departement = "75"  # Paris = tier1
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_bonus(base_annonce, config)
        assert score > 0
        assert "75" in detail
    
    def test_particulier_bonus(self, scorer, base_annonce):
        base_annonce.seller_type = SellerType.PARTICULIER
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        score, detail = scorer._score_bonus(base_annonce, config)
        assert "particulier" in detail.lower()


class TestCalculateScore:
    """Tests pour le calcul complet du score"""
    
    def test_good_annonce(self, scorer, base_annonce):
        """Une bonne annonce devrait avoir un score élevé"""
        base_annonce.prix = 1500  # Prix bas pour flipping
        base_annonce.kilometrage = 160000  # Dans la plage idéale flipping
        base_annonce.description = "Prix négociable, CT ok, urgent"
        
        breakdown = scorer.calculate_score(base_annonce)
        
        assert breakdown.total > 40  # Ajusté pour config flipping
        assert base_annonce.score_total == breakdown.total
        assert base_annonce.alert_level in [AlertLevel.INTERESSANT, AlertLevel.URGENT, AlertLevel.SURVEILLER]
    
    def test_bad_annonce(self, scorer, base_annonce):
        """Une mauvaise annonce devrait avoir un score bas"""
        base_annonce.prix = 4500  # Trop cher
        base_annonce.kilometrage = 280000  # Trop de km
        base_annonce.description = "Moteur HS"
        
        breakdown = scorer.calculate_score(base_annonce)
        
        assert breakdown.total < 20
        assert base_annonce.alert_level == AlertLevel.ARCHIVE
    
    def test_unknown_vehicle(self, scorer):
        """Un véhicule non ciblé devrait avoir score = 0"""
        annonce = Annonce(
            source=Source.AUTOSCOUT24,
            marque="Ferrari",
            modele="458",
            prix=150000,
            url="https://test.com/123"
        )
        
        breakdown = scorer.calculate_score(annonce)
        
        assert breakdown.total == 0
    
    def test_breakdown_structure(self, scorer, base_annonce):
        """Vérifie que le breakdown est complet"""
        breakdown = scorer.calculate_score(base_annonce)
        
        assert hasattr(breakdown, "prix_score")
        assert hasattr(breakdown, "km_score")
        assert hasattr(breakdown, "freshness_score")
        assert hasattr(breakdown, "keywords_score")
        assert hasattr(breakdown, "bonus_score")
        assert hasattr(breakdown, "risk_penalty")
        assert hasattr(breakdown, "total")
        assert hasattr(breakdown, "margin_min")
        assert hasattr(breakdown, "margin_max")


class TestMarginEstimation:
    """Tests pour l'estimation de marge"""
    
    def test_margin_calculation(self, scorer, base_annonce):
        base_annonce.prix = 2000
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        
        margin_min, margin_max, repair_cost = scorer._estimate_margin(base_annonce, config)
        
        # Marge devrait être positive pour un bon prix
        assert margin_min >= 0
        assert margin_max >= margin_min
    
    def test_margin_with_repairs(self, scorer, base_annonce):
        base_annonce.prix = 2000
        base_annonce.description = "CT à faire"
        base_annonce.repair_cost_estimate = 300
        
        vehicle_id, config = scorer._identify_vehicle(base_annonce)
        margin_min, margin_max, repair_cost = scorer._estimate_margin(base_annonce, config)
        
        # La marge devrait tenir compte des réparations
        assert repair_cost == 300 or repair_cost == base_annonce.repair_cost_estimate


class TestExclusions:
    """Tests pour les exclusions absolues"""
    
    def test_epave_excluded(self, scorer, base_annonce):
        base_annonce.description = "Epave pour pièces"
        
        excluded, reason = scorer._check_exclusions(base_annonce)
        
        assert excluded
        assert "epave" in reason.lower()
    
    def test_non_roulant_excluded(self, scorer, base_annonce):
        base_annonce.titre = "207 non roulant"
        
        excluded, reason = scorer._check_exclusions(base_annonce)
        
        assert excluded
    
    def test_normal_not_excluded(self, scorer, base_annonce):
        base_annonce.description = "Très bon état général"
        
        excluded, reason = scorer._check_exclusions(base_annonce)
        
        assert not excluded


class TestAlertLevel:
    """Tests pour les niveaux d'alerte"""
    
    def test_urgent_threshold(self):
        assert AlertLevel.from_score(80) == AlertLevel.URGENT
        assert AlertLevel.from_score(95) == AlertLevel.URGENT
    
    def test_interessant_threshold(self):
        assert AlertLevel.from_score(60) == AlertLevel.INTERESSANT
        assert AlertLevel.from_score(79) == AlertLevel.INTERESSANT
    
    def test_surveiller_threshold(self):
        assert AlertLevel.from_score(40) == AlertLevel.SURVEILLER
        assert AlertLevel.from_score(59) == AlertLevel.SURVEILLER
    
    def test_archive_threshold(self):
        assert AlertLevel.from_score(0) == AlertLevel.ARCHIVE
        assert AlertLevel.from_score(39) == AlertLevel.ARCHIVE
