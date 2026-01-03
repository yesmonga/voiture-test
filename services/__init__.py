"""
Services package - V2
"""

# New V2 services
from .scoring import ScoringService, get_scoring_service
from .normalize import NormalizeService, get_normalize_service

# Legacy imports (for backward compatibility)
try:
    from .scorer import ScoringService as ScoringServiceV1
    from .notifier import NotificationService
    from .deduplicator import DeduplicationService
    from .analyzer import AnalyzerService
    _legacy_available = True
except ImportError:
    _legacy_available = False

__all__ = [
    # V2
    "ScoringService", "get_scoring_service",
    "NormalizeService", "get_normalize_service",
]

if _legacy_available:
    __all__.extend(["ScoringServiceV1", "NotificationService", "DeduplicationService", "AnalyzerService"])
