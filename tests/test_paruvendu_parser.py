"""
Tests for ParuVendu scraper parser
"""

import pytest
from scrapers.paruvendu_v1 import (
    ParuVenduIndexScraper, ParuVenduDetailScraper, ParuVenduConfig
)
from models.enums import Source


@pytest.fixture
def scraper():
    return ParuVenduIndexScraper()


@pytest.fixture
def config_scraper():
    config = ParuVenduConfig(
        marque="peugeot",
        modele="207",
        prix_min=0,
        prix_max=2000,
        km_min=150000,
        km_max=180000,
        annee_min=2006,
        annee_max=2014,
        carburant="diesel",
    )
    return ParuVenduIndexScraper(config)


class TestParuVenduConfig:
    """Tests pour la configuration"""
    
    def test_default_config(self):
        config = ParuVenduConfig()
        assert config.marque == "peugeot"
        assert config.prix_max == 2000
        assert config.km_max == 180000
    
    def test_custom_config(self):
        config = ParuVenduConfig(
            marque="renault",
            modele="clio",
            prix_max=3000,
        )
        assert config.marque == "renault"
        assert config.modele == "clio"
        assert config.prix_max == 3000


class TestParuVenduURLBuilder:
    """Tests pour la construction d'URL"""
    
    def test_build_search_url_basic(self, config_scraper):
        url = config_scraper.build_search_url(page=1)
        
        assert "paruvendu.fr" in url
        assert "auto-moto/voiture" in url
        assert "px1=2000" in url
        assert "km0=150000" in url
        assert "km1=180000" in url
    
    def test_build_search_url_pagination(self, config_scraper):
        url1 = config_scraper.build_search_url(page=1)
        url2 = config_scraper.build_search_url(page=2)
        
        assert "p=2" in url2
    
    def test_build_search_url_carburant_diesel(self, scraper):
        scraper.config.carburant = "diesel"
        url = scraper.build_search_url()
        assert "ca=D" in url
    
    def test_build_search_url_carburant_essence(self, scraper):
        scraper.config.carburant = "essence"
        url = scraper.build_search_url()
        assert "ca=E" in url
    
    def test_build_search_url_particulier(self, scraper):
        scraper.config.particulier_only = True
        url = scraper.build_search_url()
        assert "ty=P" in url
    
    def test_build_search_url_marque(self, scraper):
        scraper.config.marque = "peugeot"
        url = scraper.build_search_url()
        assert "ma0=PEUGEOT" in url


class TestParuVenduDetailScraper:
    """Tests pour le detail scraper"""
    
    def test_init(self):
        scraper = ParuVenduDetailScraper()
        assert scraper._client is None


class TestParuVenduMarquesCodes:
    """Tests pour les codes marques"""
    
    def test_marques_mapping(self, scraper):
        assert "peugeot" in scraper.MARQUES_CODES
        assert "renault" in scraper.MARQUES_CODES
        assert scraper.MARQUES_CODES["peugeot"] == "PEUGEOT"
    
    def test_carburants_mapping(self, scraper):
        assert "diesel" in scraper.CARBURANTS
        assert "essence" in scraper.CARBURANTS
        assert scraper.CARBURANTS["diesel"] == "D"
        assert scraper.CARBURANTS["essence"] == "E"
