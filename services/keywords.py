"""
Keywords Service - Matching mots-clés avec regex normalisé
- Suppression accents
- Frontières de mots (\b)
- Variantes (ct ok, ctok, ct: ok)
- Détection fiable sans faux positifs
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from config.settings import CONFIG_DIR


def load_keywords_config() -> dict[str, Any]:
    """Charge la config des mots-clés"""
    path = CONFIG_DIR / "keywords.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def remove_accents(text: str) -> str:
    """Supprime les accents d'un texte"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def normalize_text(text: str) -> str:
    """
    Normalise un texte pour le matching:
    - minuscules
    - accents supprimés
    - ponctuation normalisée
    - espaces multiples → simple
    """
    if not text:
        return ""
    
    text = text.lower()
    text = remove_accents(text)
    
    # Normaliser certains caractères
    text = text.replace("'", " ")
    text = text.replace("-", " ")
    text = text.replace(":", " ")
    text = text.replace("/", " ")
    
    # Supprimer la ponctuation mais garder les lettres/chiffres/espaces
    text = re.sub(r"[^\w\s]", " ", text)
    
    # Normaliser les espaces
    text = re.sub(r"\s+", " ", text).strip()
    
    return text


@dataclass
class KeywordMatch:
    """Résultat d'un match de mot-clé"""
    keyword_id: str
    category: str  # "opportunite" ou "risque"
    matched_text: str
    bonus: int = 0
    penalty: int = 0
    cost_estimate: int = 0
    severity: str = "low"
    description: str = ""


@dataclass 
class CompiledKeyword:
    """Mot-clé compilé avec ses variantes regex"""
    keyword_id: str
    category: str
    patterns: list[re.Pattern]
    bonus: int = 0
    penalty: int = 0
    cost_estimate: int = 0
    severity: str = "low"
    description: str = ""


class KeywordMatcher:
    """
    Service de matching mots-clés avec regex normalisé.
    
    Améliore la détection par rapport au simple `in`:
    - Gère les accents (contrôle = controle)
    - Frontières de mots (évite "turbo" dans "turbo-diesel")
    - Variantes (ct ok, ctok, ct: ok, ct vierge)
    """
    
    def __init__(self):
        self.config = load_keywords_config()
        
        # Compiler les patterns
        self._opportunite: list[CompiledKeyword] = []
        self._risque: list[CompiledKeyword] = []
        self._exclusions: list[re.Pattern] = []
        
        self._compile_keywords()
    
    def _compile_keywords(self):
        """Compile tous les patterns regex"""
        
        # Opportunités
        for kw_id, kw_config in self.config.get("opportunite", {}).items():
            patterns = self._build_patterns(kw_config.get("patterns", []))
            self._opportunite.append(CompiledKeyword(
                keyword_id=kw_id,
                category="opportunite",
                patterns=patterns,
                bonus=kw_config.get("bonus", 5),
                description=kw_config.get("description", "")
            ))
        
        # Risques
        for kw_id, kw_config in self.config.get("risque", {}).items():
            patterns = self._build_patterns(kw_config.get("patterns", []))
            self._risque.append(CompiledKeyword(
                keyword_id=kw_id,
                category="risque",
                patterns=patterns,
                penalty=kw_config.get("penalty", -10),
                cost_estimate=kw_config.get("cost_estimate", 0),
                severity=kw_config.get("severity", "medium"),
                description=kw_config.get("description", "")
            ))
        
        # Exclusions
        exclusion_patterns = self.config.get("exclusions", {}).get("patterns", [])
        self._exclusions = self._build_patterns(exclusion_patterns)
        
        # Ajouter des variantes automatiques
        self._add_common_variants()
    
    def _build_patterns(self, raw_patterns: list[str]) -> list[re.Pattern]:
        """
        Construit des patterns regex avec frontières de mots.
        Les patterns sont normalisés (sans accents).
        """
        compiled = []
        for pattern in raw_patterns:
            # Normaliser le pattern
            normalized = remove_accents(pattern.lower())
            
            # Échapper les caractères spéciaux regex (sauf ceux déjà dans le pattern)
            if not any(c in pattern for c in r"\.*+?[](){}|^$"):
                normalized = re.escape(normalized)
            
            # Ajouter frontières de mots si pas déjà présentes
            if not normalized.startswith(r"\b") and not normalized.startswith("^"):
                normalized = r"\b" + normalized
            if not normalized.endswith(r"\b") and not normalized.endswith("$"):
                normalized = normalized + r"\b"
            
            try:
                compiled.append(re.compile(normalized, re.IGNORECASE))
            except re.error as e:
                print(f"⚠️ Invalid regex pattern '{pattern}': {e}")
        
        return compiled
    
    def _add_common_variants(self):
        """Ajoute des variantes courantes automatiquement"""
        
        # Variantes CT (contrôle technique) - plus permissif
        ct_patterns = [
            r"\bct\s*(ok|vierge|recent|neuf|valide|fait|passe)\b",
            r"\bcontrole\s*technique\s*(ok|vierge|recent|neuf|valide|fait|passe)\b",
            r"\bct\s*[:\-]?\s*(ok|vierge|recent)\b",
            r"\bct\s*ok\b",
            r"\bctok\b",
            r"\bc\.?t\.?\s*(ok|vierge)\b",
        ]
        
        # Vérifier si pas déjà présent
        existing_ids = {kw.keyword_id for kw in self._opportunite}
        if "ct_ok" not in existing_ids:
            self._opportunite.append(CompiledKeyword(
                keyword_id="ct_ok",
                category="opportunite",
                patterns=[re.compile(p, re.IGNORECASE) for p in ct_patterns],
                bonus=8,
                description="CT OK/vierge/récent"
            ))
        
        # Variantes urgence (plus permissif)
        urgent_patterns = [
            r"\burgent\w*\b",  # urgent, urgente, etc.
            r"\bvente\s*(urgente|rapide)\b",
            r"\bdoit\s+partir\b",
            r"\ba\s+saisir\b",
            r"\boccasion\s+a\s+saisir\b",
            r"\bdemenagement\b",
        ]
        if "urgent_vente" not in existing_ids:
            self._opportunite.append(CompiledKeyword(
                keyword_id="urgent_vente",
                category="opportunite",
                patterns=[re.compile(p, re.IGNORECASE) for p in urgent_patterns],
                bonus=10,
                description="Vente urgente/rapide"
            ))
        
        # Variantes négociable
        nego_patterns = [
            r"\bnego(ciable)?\b",
            r"\ba\s+debattre\b",
            r"\bprix\s+a\s+discuter\b",
            r"\bouvert\s+(aux\s+)?propositions?\b",
        ]
        if "negociable" not in existing_ids:
            self._opportunite.append(CompiledKeyword(
                keyword_id="negociable",
                category="opportunite",
                patterns=[re.compile(p, re.IGNORECASE) for p in nego_patterns],
                bonus=5,
                description="Prix négociable"
            ))
        
        # Variantes risques - moteur
        moteur_risk_patterns = [
            r"\bmoteur\s*(hs|mort|casse|a\s+refaire)\b",
            r"\bne\s+(demarre|roule)\s+(plus|pas)\b",
            r"\bpour\s+pieces\b",
        ]
        existing_risk_ids = {kw.keyword_id for kw in self._risque}
        if "moteur_hs" not in existing_risk_ids:
            self._risque.append(CompiledKeyword(
                keyword_id="moteur_hs",
                category="risque",
                patterns=[re.compile(p, re.IGNORECASE) for p in moteur_risk_patterns],
                penalty=-30,
                cost_estimate=2000,
                severity="critical",
                description="Moteur HS/cassé"
            ))
        
        # Variantes risques - CT refusé (patterns plus permissifs)
        ct_risk_patterns = [
            r"\bct\s*(refuse|refus|a\s*faire|expire)\b",
            r"\bcontre\s*visite\b",
            r"\bcontrevisite\b",
            r"\bsans\s+ct\b",
            r"\bct\s+expire\b",
        ]
        if "ct_refuse" not in existing_risk_ids:
            self._risque.append(CompiledKeyword(
                keyword_id="ct_refuse",
                category="risque",
                patterns=[re.compile(p, re.IGNORECASE) for p in ct_risk_patterns],
                penalty=-15,
                cost_estimate=400,
                severity="medium",
                description="CT refusé/à faire"
            ))
    
    def find_matches(self, text: str) -> tuple[list[KeywordMatch], list[KeywordMatch]]:
        """
        Trouve tous les mots-clés dans un texte.
        
        Returns:
            Tuple (opportunités, risques)
        """
        if not text:
            return [], []
        
        # Normaliser le texte
        normalized = normalize_text(text)
        
        opportunities = []
        risks = []
        
        # Chercher les opportunités
        for kw in self._opportunite:
            for pattern in kw.patterns:
                match = pattern.search(normalized)
                if match:
                    opportunities.append(KeywordMatch(
                        keyword_id=kw.keyword_id,
                        category="opportunite",
                        matched_text=match.group(0),
                        bonus=kw.bonus,
                        description=kw.description
                    ))
                    break  # Un seul match par keyword
        
        # Chercher les risques
        for kw in self._risque:
            for pattern in kw.patterns:
                match = pattern.search(normalized)
                if match:
                    risks.append(KeywordMatch(
                        keyword_id=kw.keyword_id,
                        category="risque",
                        matched_text=match.group(0),
                        penalty=kw.penalty,
                        cost_estimate=kw.cost_estimate,
                        severity=kw.severity,
                        description=kw.description
                    ))
                    break
        
        return opportunities, risks
    
    def is_excluded(self, text: str) -> tuple[bool, str]:
        """
        Vérifie si le texte contient un mot-clé d'exclusion.
        
        Returns:
            (is_excluded, reason)
        """
        if not text:
            return False, ""
        
        normalized = normalize_text(text)
        
        for pattern in self._exclusions:
            match = pattern.search(normalized)
            if match:
                return True, f"Exclusion: {match.group(0)}"
        
        return False, ""
    
    def calculate_scores(self, text: str) -> tuple[int, int, int, list[str], list[str]]:
        """
        Calcule les scores basés sur les mots-clés.
        
        Returns:
            (bonus_total, penalty_total, cost_estimate, opportunity_ids, risk_ids)
        """
        opportunities, risks = self.find_matches(text)
        
        bonus_total = sum(m.bonus for m in opportunities)
        penalty_total = sum(m.penalty for m in risks)  # Déjà négatif
        cost_estimate = sum(m.cost_estimate for m in risks)
        
        opportunity_ids = [m.keyword_id for m in opportunities]
        risk_ids = [m.keyword_id for m in risks]
        
        return bonus_total, penalty_total, cost_estimate, opportunity_ids, risk_ids
    
    def get_severity_max(self, text: str) -> str:
        """Retourne la sévérité maximale des risques détectés"""
        _, risks = self.find_matches(text)
        
        if not risks:
            return "none"
        
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        max_severity = max(risks, key=lambda r: severity_order.get(r.severity, 0))
        
        return max_severity.severity


# Instance globale
_keyword_matcher: Optional[KeywordMatcher] = None


def get_keyword_matcher() -> KeywordMatcher:
    """Retourne l'instance du matcher de mots-clés"""
    global _keyword_matcher
    if _keyword_matcher is None:
        _keyword_matcher = KeywordMatcher()
    return _keyword_matcher
