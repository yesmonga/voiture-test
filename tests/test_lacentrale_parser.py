"""
Tests for La Centrale scraper parser
"""

import pytest
from scrapers.lacentrale_v1 import (
    LaCentraleIndexScraper, LaCentraleDetailScraper, LaCentraleConfig
)
from models.enums import Source


@pytest.fixture
def scraper():
    return LaCentraleIndexScraper()


@pytest.fixture
def config_scraper():
    config = LaCentraleConfig(
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
    return LaCentraleIndexScraper(config)


class TestLaCentraleConfig:
    """Tests pour la configuration"""
    
    def test_default_config(self):
        config = LaCentraleConfig()
        assert config.marque == "peugeot"
        assert config.prix_max == 2000
        assert config.km_max == 180000
    
    def test_custom_config(self):
        config = LaCentraleConfig(
            marque="renault",
            modele="clio",
            prix_max=3000,
        )
        assert config.marque == "renault"
        assert config.modele == "clio"
        assert config.prix_max == 3000


class TestLaCentraleURLBuilder:
    """Tests pour la construction d'URL"""
    
    def test_build_search_url_basic(self, config_scraper):
        url = config_scraper.build_search_url(page=1)
        
        assert "lacentrale.fr" in url
        assert "listing" in url
        assert "priceMax=2000" in url
        assert "mileageMin=150000" in url
        assert "mileageMax=180000" in url
    
    def test_build_search_url_pagination(self, config_scraper):
        url1 = config_scraper.build_search_url(page=1)
        url2 = config_scraper.build_search_url(page=2)
        
        assert "page=2" in url2
        assert "page=" not in url1 or "page=1" not in url1
    
    def test_build_search_url_carburant(self, scraper):
        scraper.config.carburant = "diesel"
        url = scraper.build_search_url()
        assert "DIESEL" in url
    
    def test_build_search_url_particulier(self, scraper):
        scraper.config.particulier_only = True
        url = scraper.build_search_url()
        assert "customerType=part" in url


class TestLaCentraleParseListing:
    """Tests pour le parsing des listings"""
    
    def test_parse_listing_complete(self, scraper):
        raw = {
            "id": "12345678",
            "title": "Peugeot 207 1.4 HDi 70ch",
            "price": {"value": 1800},
            "vehicle": {
                "make": "Peugeot",
                "model": "207",
                "mileage": {"value": 165000},
                "year": "2010",
                "energy": "Diesel",
            },
            "location": {
                "city": "Paris",
                "zipCode": "75012",
            },
            "url": "/auto-occasion-annonce-12345678.html",
        }
        
        result = scraper._parse_listing(raw)
        
        assert result is not None
        assert result.source == Source.LACENTRALE
        assert result.source_listing_id == "12345678"
        assert result.prix == 1800
        assert result.kilometrage == 165000
        assert result.annee == 2010
        assert result.departement == "75"
        assert "lacentrale.fr" in result.url
    
    def test_parse_listing_minimal(self, scraper):
        raw = {
            "id": "99999999",
            "title": "Voiture occasion",
        }
        
        result = scraper._parse_listing(raw)
        
        assert result is not None
        assert result.source_listing_id == "99999999"
        assert result.prix is None
    
    def test_parse_listing_without_id(self, scraper):
        raw = {
            "title": "Sans ID",
            "price": {"value": 1000},
        }
        
        result = scraper._parse_listing(raw)
        assert result is None
    
    def test_parse_listing_price_variations(self, scraper):
        # Prix en dict
        raw1 = {"id": "1", "price": {"value": 1500}}
        result1 = scraper._parse_listing(raw1)
        assert result1.prix == 1500
        
        # Prix en int
        raw2 = {"id": "2", "price": 2000}
        result2 = scraper._parse_listing(raw2)
        assert result2.prix == 2000
        
        # Prix en string
        raw3 = {"id": "3", "price": "1 800 €"}
        result3 = scraper._parse_listing(raw3)
        assert result3.prix == 1800


class TestLaCentraleJsonExtraction:
    """Tests pour l'extraction JSON"""
    
    def test_find_listings_in_json_direct(self, scraper):
        data = {
            "listings": [
                {"id": "1", "price": {"value": 1000}},
                {"id": "2", "price": {"value": 2000}},
            ]
        }
        
        listings = scraper._find_listings_in_json(data)
        assert len(listings) == 2
    
    def test_find_listings_in_json_nested(self, scraper):
        data = {
            "props": {
                "pageProps": {
                    "searchResult": {
                        "listings": [
                            {"id": "1", "price": {"value": 1500}},
                        ]
                    }
                }
            }
        }
        
        listings = scraper._find_listings_in_json(data)
        assert len(listings) >= 1
    
    def test_find_listings_in_json_empty(self, scraper):
        data = {"empty": True}
        listings = scraper._find_listings_in_json(data)
        assert len(listings) == 0


class TestLaCentraleDetailScraper:
    """Tests pour le detail scraper"""
    
    def test_init(self):
        scraper = LaCentraleDetailScraper()
        assert scraper._client is None
