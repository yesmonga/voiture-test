"""
Tests pour le parser AutoScout24 V2
Vérifie l'extraction __NEXT_DATA__ et le parsing des annonces
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path to avoid __init__.py import chain issues
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import directly to avoid old code dependencies
from scrapers.autoscout24_v2 import (
    AutoScout24IndexScraper,
    AutoScout24DetailScraper,
    AutoScout24Config,
)
from models.enums import Source


class TestAutoScout24IndexScraper:
    """Tests pour l'index scraper"""
    
    def test_build_search_url(self):
        """Test construction URL de recherche"""
        config = AutoScout24Config(
            marque="peugeot",
            modele="207",
            prix_min=1000,
            prix_max=4000,
            km_max=150000,
            annee_min=2008,
            annee_max=2013,
            carburant="diesel",
            zip_code="75001",
            radius_km=100,
            particulier_only=True,
        )
        scraper = AutoScout24IndexScraper(config)
        url = scraper.build_search_url(page=1)
        
        assert "autoscout24.fr" in url
        assert "peugeot" in url
        assert "207" in url
        assert "pricefrom=1000" in url
        assert "priceto=4000" in url
        assert "kmto=150000" in url
        assert "fregfrom=2008" in url
        assert "fregto=2013" in url
        assert "fuel=D" in url
        assert "custtype=P" in url
    
    def test_extract_next_data_mock(self):
        """Test extraction __NEXT_DATA__ avec HTML mock"""
        scraper = AutoScout24IndexScraper()
        
        mock_html = '''
        <!DOCTYPE html>
        <html>
        <head></head>
        <body>
            <script id="__NEXT_DATA__" type="application/json">
            {
                "props": {
                    "pageProps": {
                        "listings": [
                            {
                                "id": "123456",
                                "title": "Peugeot 207 1.6 HDi",
                                "price": {"value": 2500},
                                "vehicle": {
                                    "make": "Peugeot",
                                    "model": "207",
                                    "mileage": 145000,
                                    "firstRegistration": "2010"
                                },
                                "location": {
                                    "city": "Paris",
                                    "zip": "75001"
                                },
                                "url": "/annonce/123456"
                            }
                        ]
                    }
                }
            }
            </script>
        </body>
        </html>
        '''
        
        next_data = scraper._extract_next_data(mock_html)
        assert next_data is not None
        assert "props" in next_data
    
    def test_find_listings_recursive(self):
        """Test recherche récursive des listings"""
        scraper = AutoScout24IndexScraper()
        
        data = {
            "deeply": {
                "nested": {
                    "listings": [
                        {
                            "id": "ABC123",
                            "price": {"value": 3000},
                            "make": "Peugeot",
                            "model": "207",
                        }
                    ]
                }
            }
        }
        
        listings = scraper._find_listings_recursive(data)
        assert len(listings) >= 1
        assert any(l.get("id") == "ABC123" for l in listings)
    
    def test_parse_listing(self):
        """Test parsing d'un listing brut"""
        scraper = AutoScout24IndexScraper()
        
        raw = {
            "id": "789XYZ",
            "title": "Renault Clio III 1.5 dCi",
            "price": {"value": 2800},
            "vehicle": {
                "make": "Renault",
                "model": "Clio",
                "mileage": 98000,
                "firstRegistration": "2012",
            },
            "location": {
                "city": "Lyon",
                "zip": "69001",
            },
            "url": "/annonce/789XYZ",
        }
        
        result = scraper._parse_listing(raw)
        
        assert result is not None
        assert result.source == Source.AUTOSCOUT24
        assert result.source_listing_id == "789XYZ"
        assert result.prix == 2800
        assert result.kilometrage == 98000
        assert result.annee == 2012
        assert result.departement == "69"
        assert "autoscout24.fr" in result.url
    
    def test_parse_listing_handles_missing_fields(self):
        """Test que le parser gère les champs manquants"""
        scraper = AutoScout24IndexScraper()
        
        # Minimum viable listing
        raw = {
            "id": "MINIMAL",
            "title": "Voiture occasion",
        }
        
        result = scraper._parse_listing(raw)
        
        assert result is not None
        assert result.source_listing_id == "MINIMAL"
        assert result.prix is None
        assert result.kilometrage is None
    
    def test_parse_listing_without_id_returns_none(self):
        """Test qu'un listing sans ID retourne None"""
        scraper = AutoScout24IndexScraper()
        
        raw = {
            "title": "Sans ID",
            "price": {"value": 1000},
        }
        
        result = scraper._parse_listing(raw)
        assert result is None


class TestAutoScout24DetailScraper:
    """Tests pour le detail scraper"""
    
    def test_init(self):
        """Test initialisation"""
        scraper = AutoScout24DetailScraper()
        assert scraper._client is None


class TestIntegration:
    """Tests d'intégration (nécessitent mock ou fixture)"""
    
    def test_full_parse_flow_mock(self):
        """Test du flow complet avec données mock"""
        scraper = AutoScout24IndexScraper()
        
        # Simule __NEXT_DATA__ typique
        mock_next_data = {
            "props": {
                "pageProps": {
                    "searchResult": {
                        "listings": [
                            {
                                "id": "L001",
                                "price": {"value": 2200},
                                "vehicle": {
                                    "make": "Peugeot",
                                    "model": "207",
                                    "mileage": 130000,
                                    "firstRegistration": "2011",
                                    "fuelType": "Diesel",
                                },
                                "location": {"city": "Paris", "zip": "75012"},
                                "url": "/d/peugeot-207/L001",
                            },
                            {
                                "id": "L002",
                                "price": {"value": 1800},
                                "vehicle": {
                                    "make": "Renault",
                                    "model": "Clio",
                                    "mileage": 155000,
                                    "firstRegistration": "2009",
                                },
                                "location": {"city": "Lyon", "zip": "69003"},
                                "url": "/d/renault-clio/L002",
                            },
                        ]
                    }
                }
            }
        }
        
        listings = scraper._find_listings_recursive(mock_next_data)
        assert len(listings) >= 2
        
        results = []
        for raw in listings:
            result = scraper._parse_listing(raw)
            if result:
                results.append(result)
        
        assert len(results) >= 2
        
        # Vérifier premier résultat
        r1 = next((r for r in results if r.source_listing_id == "L001"), None)
        assert r1 is not None
        assert r1.prix == 2200
        assert r1.kilometrage == 130000
        assert r1.annee == 2011
        assert r1.departement == "75"


if __name__ == "__main__":
    import sys
    
    # Run tests manually
    passed = 0
    failed = 0
    
    test_classes = [
        TestAutoScout24IndexScraper(),
        TestAutoScout24DetailScraper(),
        TestIntegration(),
    ]
    
    for test_class in test_classes:
        class_name = test_class.__class__.__name__
        print(f"\n{class_name}")
        print("-" * 40)
        
        for method_name in dir(test_class):
            if method_name.startswith("test_"):
                method = getattr(test_class, method_name)
                try:
                    method()
                    print(f"  ✅ {method_name}")
                    passed += 1
                except AssertionError as e:
                    print(f"  ❌ {method_name}: {e}")
                    failed += 1
                except Exception as e:
                    print(f"  ❌ {method_name}: {type(e).__name__}: {e}")
                    failed += 1
    
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    
    sys.exit(0 if failed == 0 else 1)
