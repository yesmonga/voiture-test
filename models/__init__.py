"""
Models package - V2 with backward compatibility
"""

# New V2 models
from .enums import Source, SellerType, AlertLevel, AnnonceStatus, Carburant, Boite, Severity
from .annonce_v2 import Annonce, ScoreBreakdown, utc_now, canonicalize_url

# Legacy imports (for backward compatibility)
try:
    from .annonce import Annonce as AnnonceV1
    from .database import Database, get_db
    _legacy_available = True
except ImportError:
    _legacy_available = False

__all__ = [
    # V2
    "Source", "SellerType", "AlertLevel", "AnnonceStatus", "Carburant", "Boite", "Severity",
    "Annonce", "ScoreBreakdown", "utc_now", "canonicalize_url",
]

if _legacy_available:
    __all__.extend(["AnnonceV1", "Database", "get_db"])
