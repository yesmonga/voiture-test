"""
Tests for normalize service
"""

import pytest
from services.normalize import NormalizeService, get_normalize_service
from models.enums import Carburant, Boite, SellerType


@pytest.fixture
def normalizer():
    return NormalizeService()


class TestParsePrice:
    """Tests pour le parsing des prix"""
    
    def test_price_standard(self, normalizer):
        assert normalizer.parse_price("2 500 €") == 2500
    
    def test_price_no_space(self, normalizer):
        assert normalizer.parse_price("2500€") == 2500
    
    def test_price_with_dots(self, normalizer):
        assert normalizer.parse_price("2.500 €") == 2500
    
    def test_price_with_comma(self, normalizer):
        assert normalizer.parse_price("2,500€") == 2500
    
    def test_price_in_text(self, normalizer):
        assert normalizer.parse_price("Prix: 3 200 € négociable") == 3200
    
    def test_price_nbsp(self, normalizer):
        # Non-breaking space
        assert normalizer.parse_price("2\u00a0500\u00a0€") == 2500
    
    def test_price_none(self, normalizer):
        assert normalizer.parse_price(None) is None
    
    def test_price_empty(self, normalizer):
        assert normalizer.parse_price("") is None
    
    def test_price_invalid(self, normalizer):
        assert normalizer.parse_price("gratuit") is None
    
    def test_price_too_low(self, normalizer):
        # < 100€ = invalide
        assert normalizer.parse_price("50 €") is None
    
    def test_price_too_high(self, normalizer):
        # > 100000€ = invalide
        assert normalizer.parse_price("150 000 €") is None


class TestParseKm:
    """Tests pour le parsing des kilométrages"""
    
    def test_km_standard(self, normalizer):
        assert normalizer.parse_km("150 000 km") == 150000
    
    def test_km_no_space(self, normalizer):
        assert normalizer.parse_km("150000km") == 150000
    
    def test_km_with_dots(self, normalizer):
        assert normalizer.parse_km("150.000 km") == 150000
    
    def test_km_in_text(self, normalizer):
        assert normalizer.parse_km("Kilométrage: 120 000 km certifié") == 120000
    
    def test_km_lowercase(self, normalizer):
        assert normalizer.parse_km("85000 KM") == 85000
    
    def test_km_none(self, normalizer):
        assert normalizer.parse_km(None) is None
    
    def test_km_invalid(self, normalizer):
        assert normalizer.parse_km("beaucoup") is None


class TestParseYear:
    """Tests pour le parsing des années"""
    
    def test_year_in_text(self, normalizer):
        assert normalizer.parse_year("Peugeot 207 année 2010") == 2010
    
    def test_year_with_slash(self, normalizer):
        assert normalizer.parse_year("Mise en circulation 01/2012") == 2012
    
    def test_year_multiple(self, normalizer):
        # Prend la plus récente
        assert normalizer.parse_year("2008-2012") == 2012
    
    def test_year_none(self, normalizer):
        assert normalizer.parse_year(None) is None


class TestParseCarburant:
    """Tests pour la détection du carburant"""
    
    def test_diesel_explicit(self, normalizer):
        assert normalizer.parse_carburant("Diesel") == Carburant.DIESEL
    
    def test_diesel_hdi(self, normalizer):
        assert normalizer.parse_carburant("1.4 HDi 70ch") == Carburant.DIESEL
    
    def test_diesel_dci(self, normalizer):
        assert normalizer.parse_carburant("1.5 dCi") == Carburant.DIESEL
    
    def test_essence_explicit(self, normalizer):
        assert normalizer.parse_carburant("Essence") == Carburant.ESSENCE
    
    def test_essence_vti(self, normalizer):
        assert normalizer.parse_carburant("1.2 VTi") == Carburant.ESSENCE
    
    def test_unknown(self, normalizer):
        assert normalizer.parse_carburant("1.4") == Carburant.UNKNOWN
    
    def test_none(self, normalizer):
        assert normalizer.parse_carburant(None) == Carburant.UNKNOWN


class TestParseBoite:
    """Tests pour la détection de la boîte"""
    
    def test_manuelle(self, normalizer):
        assert normalizer.parse_boite("Boîte manuelle") == Boite.MANUELLE
    
    def test_automatique(self, normalizer):
        assert normalizer.parse_boite("BVA") == Boite.AUTOMATIQUE
    
    def test_unknown(self, normalizer):
        assert normalizer.parse_boite("5 vitesses") == Boite.UNKNOWN


class TestParseDepartement:
    """Tests pour l'extraction du département"""
    
    def test_from_cp(self, normalizer):
        assert normalizer.parse_departement("75001 Paris") == "75"
    
    def test_from_parentheses(self, normalizer):
        assert normalizer.parse_departement("Créteil (94)") == "94"
    
    def test_none(self, normalizer):
        assert normalizer.parse_departement(None) is None


class TestParseSellerType:
    """Tests pour la détection du type de vendeur"""
    
    def test_particulier(self, normalizer):
        assert normalizer.parse_seller_type("Particulier") == SellerType.PARTICULIER
    
    def test_professionnel(self, normalizer):
        assert normalizer.parse_seller_type("Professionnel") == SellerType.PROFESSIONNEL
    
    def test_garage(self, normalizer):
        assert normalizer.parse_seller_type("Garage Auto Plus") == SellerType.PROFESSIONNEL
    
    def test_unknown(self, normalizer):
        assert normalizer.parse_seller_type("Jean Dupont") == SellerType.UNKNOWN


class TestParseTitle:
    """Tests pour le parsing des titres"""
    
    def test_full_title(self, normalizer):
        marque, modele, version = normalizer.parse_title("Peugeot 207 1.4 HDi 70ch Active")
        assert marque == "Peugeot"
        assert modele == "207"
        assert "1.4" in version or "HDi" in version
    
    def test_simple_title(self, normalizer):
        marque, modele, version = normalizer.parse_title("Renault Clio")
        assert marque == "Renault"
        assert modele == "Clio"
    
    def test_empty(self, normalizer):
        assert normalizer.parse_title("") == ("", "", "")
    
    def test_none(self, normalizer):
        assert normalizer.parse_title(None) == ("", "", "")
    
    def test_title_starts_with_model_207(self, normalizer):
        """Test inférence marque quand titre commence par modèle (207 -> Peugeot)"""
        marque, modele, version = normalizer.parse_title("207 1.4 HDi 70ch")
        assert marque == "Peugeot"
        assert modele == "207"
        assert "1.4" in version or "HDi" in version
    
    def test_title_starts_with_model_clio(self, normalizer):
        """Test inférence marque (Clio -> Renault)"""
        marque, modele, version = normalizer.parse_title("Clio 3 1.5 dCi 85ch")
        assert marque == "Renault"
        assert modele == "Clio"
    
    def test_title_starts_with_model_c3(self, normalizer):
        """Test inférence marque (C3 -> Citroën)"""
        marque, modele, version = normalizer.parse_title("C3 1.4 HDi 70")
        assert marque == "Citroën"
        assert modele == "C3"
    
    def test_title_starts_with_model_sandero(self, normalizer):
        """Test inférence marque (Sandero -> Dacia)"""
        marque, modele, version = normalizer.parse_title("Sandero Stepway 1.5 dCi")
        assert marque == "Dacia"
        assert modele == "Sandero"


class TestNormalizeText:
    """Tests pour la normalisation de texte"""
    
    def test_lowercase(self, normalizer):
        assert normalizer.normalize_text("PEUGEOT") == "peugeot"
    
    def test_strip(self, normalizer):
        assert normalizer.normalize_text("  test  ") == "test"
    
    def test_multiple_spaces(self, normalizer):
        assert normalizer.normalize_text("a   b  c") == "a b c"


class TestFormatting:
    """Tests pour le formatage"""
    
    def test_format_price_fr(self, normalizer):
        assert normalizer.format_price_fr(2500) == "2 500 €"
    
    def test_format_price_fr_large(self, normalizer):
        assert normalizer.format_price_fr(12500) == "12 500 €"
    
    def test_format_price_fr_none(self, normalizer):
        assert normalizer.format_price_fr(None) == "N/C"
    
    def test_format_km_fr(self, normalizer):
        assert normalizer.format_km_fr(150000) == "150 000 km"
    
    def test_format_km_fr_none(self, normalizer):
        assert normalizer.format_km_fr(None) == "N/C"
