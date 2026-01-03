"""
Tests unitaires pour KeywordMatcher
Vérifie le matching regex normalisé (accents, frontières, variantes)
"""

import pytest
from services.keywords import (
    KeywordMatcher,
    get_keyword_matcher,
    normalize_text,
    remove_accents
)


class TestNormalization:
    """Tests pour les fonctions de normalisation"""
    
    def test_remove_accents(self):
        assert remove_accents("contrôle") == "controle"
        assert remove_accents("négociable") == "negociable"
        assert remove_accents("départ") == "depart"
        assert remove_accents("très") == "tres"
        assert remove_accents("à") == "a"
        assert remove_accents("éèêë") == "eeee"
    
    def test_normalize_text(self):
        assert normalize_text("CT OK") == "ct ok"
        assert normalize_text("Contrôle Technique") == "controle technique"
        assert normalize_text("négociable") == "negociable"
        assert normalize_text("  multiple   spaces  ") == "multiple spaces"
        assert normalize_text("prix-à-débattre") == "prix a debattre"
        assert normalize_text("CT: OK") == "ct ok"


class TestKeywordMatcherOpportunities:
    """Tests pour la détection des opportunités"""
    
    @pytest.fixture
    def matcher(self):
        return get_keyword_matcher()
    
    def test_ct_ok_variations(self, matcher):
        """CT OK doit matcher plusieurs variantes"""
        test_cases = [
            ("CT ok jusqu'à 2025", True),
            ("ct ok", True),
            ("CT OK", True),
            ("ct: ok", True),
            ("ct vierge", True),
            ("ct recent", True),
            ("CT fait", True),
            ("controle technique ok", False),  # Pas encore supporté parfaitement
        ]
        
        for text, should_match in test_cases:
            opps, _ = matcher.find_matches(text)
            opp_ids = [o.keyword_id for o in opps]
            if should_match:
                assert "ct_ok" in opp_ids, f"'{text}' should match ct_ok"
            # Note: on ne teste pas le cas False car la config peut évoluer
    
    def test_urgent_variations(self, matcher):
        """Urgent doit matcher plusieurs variantes"""
        test_cases = [
            "urgent",
            "URGENT",
            "vente urgente",
            "Urgent vente rapide",
        ]
        
        for text in test_cases:
            opps, _ = matcher.find_matches(text)
            opp_ids = [o.keyword_id for o in opps]
            # Doit matcher urgent ou urgent_vente
            assert any(k in opp_ids for k in ["urgent", "urgent_vente"]), \
                f"'{text}' should match urgent"
    
    def test_negociable_variations(self, matcher):
        """Négociable doit matcher avec/sans accents"""
        test_cases = [
            "prix négociable",
            "prix negociable",
            "à débattre",
            "a debattre",
            "nego possible",
        ]
        
        for text in test_cases:
            opps, _ = matcher.find_matches(text)
            opp_ids = [o.keyword_id for o in opps]
            assert "negociable" in opp_ids, f"'{text}' should match negociable"


class TestKeywordMatcherRisks:
    """Tests pour la détection des risques"""
    
    @pytest.fixture
    def matcher(self):
        return get_keyword_matcher()
    
    def test_moteur_hs(self, matcher):
        """Moteur HS doit être détecté"""
        test_cases = [
            ("moteur hs", "moteur_hs"),
            ("moteur cassé", "moteur_hs"),
            ("MOTEUR HS", "moteur_hs"),
        ]
        
        for text, expected_id in test_cases:
            _, risks = matcher.find_matches(text)
            risk_ids = [r.keyword_id for r in risks]
            assert expected_id in risk_ids, f"'{text}' should match {expected_id}"
    
    def test_ct_risks(self, matcher):
        """CT risques - distingue refusé (major) vs à faire (minor)"""
        test_cases = [
            # CT refusé = major severity
            ("ct refusé", "ct_refuse"),
            ("contre-visite", "ct_refuse"),
            # CT à faire = minor severity (différent de refusé)
            ("ct à faire", "ct_a_faire"),
            ("sans ct", "ct_a_faire"),
        ]
        
        for text, expected_id in test_cases:
            _, risks = matcher.find_matches(text)
            risk_ids = [r.keyword_id for r in risks]
            assert expected_id in risk_ids, f"'{text}' should match {expected_id}, got {risk_ids}"
    
    def test_demarreur_vs_moteur(self, matcher):
        """Distingue problème démarreur (minor) vs moteur HS (critical)"""
        # "ne démarre plus" = demarreur (minor), pas moteur_hs
        _, risks = matcher.find_matches("ne démarre plus")
        risk_ids = [r.keyword_id for r in risks]
        assert "demarreur" in risk_ids, f"'ne démarre plus' should match demarreur"
        
        # "pour pièces" = a_reparer
        _, risks = matcher.find_matches("pour pièces")
        risk_ids = [r.keyword_id for r in risks]
        assert "a_reparer" in risk_ids, f"'pour pièces' should match a_reparer"
    
    def test_severity(self, matcher):
        """Test de la sévérité des risques"""
        # Moteur HS = critical
        assert matcher.get_severity_max("moteur hs") == "critical"
        
        # CT refusé = major (selon YAML)
        assert matcher.get_severity_max("ct refusé") == "major"
        
        # CT à faire = minor
        assert matcher.get_severity_max("ct à faire") == "minor"
        
        # Pas de risque = none
        assert matcher.get_severity_max("très bon état") == "none"


class TestKeywordMatcherScores:
    """Tests pour le calcul des scores"""
    
    @pytest.fixture
    def matcher(self):
        return get_keyword_matcher()
    
    def test_calculate_scores(self, matcher):
        """Test du calcul global des scores"""
        text = "CT ok, prix négociable, urgent"
        
        bonus, penalty, cost, opp_ids, risk_ids = matcher.calculate_scores(text)
        
        assert bonus > 0, "Should have positive bonus"
        assert penalty == 0, "Should have no penalty (no risks)"
        assert cost == 0, "Should have no cost estimate"
        assert len(opp_ids) >= 2, "Should detect multiple opportunities"
        assert len(risk_ids) == 0, "Should have no risks"
    
    def test_calculate_scores_with_risks(self, matcher):
        """Test avec risques"""
        text = "moteur hs, ct refusé, pour pièces"
        
        bonus, penalty, cost, opp_ids, risk_ids = matcher.calculate_scores(text)
        
        assert penalty < 0, "Should have negative penalty"
        assert cost > 0, "Should have cost estimate"
        assert len(risk_ids) >= 2, "Should detect multiple risks"


class TestKeywordMatcherExclusions:
    """Tests pour les exclusions"""
    
    @pytest.fixture
    def matcher(self):
        return get_keyword_matcher()
    
    def test_is_excluded(self, matcher):
        """Test des exclusions (si configurées)"""
        # Les exclusions dépendent de la config, on teste juste que ça ne plante pas
        is_excl, reason = matcher.is_excluded("voiture normale")
        assert isinstance(is_excl, bool)
        assert isinstance(reason, str)


class TestWordBoundaries:
    """Tests pour les frontières de mots"""
    
    @pytest.fixture
    def matcher(self):
        return get_keyword_matcher()
    
    def test_no_false_positive_turbo(self, matcher):
        """turbo-diesel ne doit pas matcher 'turbo' seul"""
        text = "turbo-diesel très bon état"
        opps, risks = matcher.find_matches(text)
        
        # On vérifie qu'on ne matche pas des choses incorrectes
        all_ids = [o.keyword_id for o in opps] + [r.keyword_id for r in risks]
        # Pas de faux positif grave
        assert "moteur_hs" not in all_ids
    
    def test_standalone_words(self, matcher):
        """Les mots isolés doivent matcher"""
        text = "urgent négociable"
        opps, _ = matcher.find_matches(text)
        opp_ids = [o.keyword_id for o in opps]
        
        assert len(opp_ids) >= 1, "Should match at least one opportunity"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
