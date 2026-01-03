"""
Rate Limiter & Circuit Breaker - Gestion anti-blocage multi-sources
Production-grade avec jitter, backoff exponentiel, et circuit breaker par source.
"""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from enum import Enum


class CircuitState(Enum):
    """États du circuit breaker"""
    CLOSED = "closed"      # Fonctionne normalement
    OPEN = "open"          # Bloqué, en pause
    HALF_OPEN = "half_open"  # Test de reprise


@dataclass
class SourceState:
    """État d'une source pour le circuit breaker"""
    name: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    blocked_until: Optional[datetime] = None
    consecutive_blocks: int = 0
    
    # Config (peut être override par source)
    failure_threshold: int = 3  # Nombre d'échecs avant OPEN
    recovery_timeout_sec: int = 120  # Temps de pause en OPEN
    half_open_success_threshold: int = 2  # Succès requis pour fermer
    
    def record_success(self):
        """Enregistre un succès"""
        self.success_count += 1
        self.last_success = datetime.now(timezone.utc)
        
        if self.state == CircuitState.HALF_OPEN:
            if self.success_count >= self.half_open_success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.consecutive_blocks = 0
                print(f"✅ Circuit {self.name}: CLOSED (recovered)")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0  # Reset après succès
    
    def record_failure(self, is_block: bool = False):
        """Enregistre un échec"""
        self.failure_count += 1
        self.last_failure = datetime.now(timezone.utc)
        
        if is_block:
            self.consecutive_blocks += 1
        
        if self.state == CircuitState.HALF_OPEN:
            # Retour en OPEN immédiat
            self._open_circuit()
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._open_circuit()
    
    def _open_circuit(self):
        """Ouvre le circuit (pause la source)"""
        self.state = CircuitState.OPEN
        
        # Backoff exponentiel basé sur les blocks consécutifs
        backoff = self.recovery_timeout_sec * (2 ** min(self.consecutive_blocks, 4))
        backoff = min(backoff, 600)  # Max 10 minutes
        
        self.blocked_until = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        self.success_count = 0
        
        print(f"⚠️ Circuit {self.name}: OPEN (paused {backoff}s)")
    
    def can_execute(self) -> bool:
        """Vérifie si on peut exécuter une requête"""
        now = datetime.now(timezone.utc)
        
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            if self.blocked_until and now >= self.blocked_until:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                print(f"🔄 Circuit {self.name}: HALF_OPEN (testing)")
                return True
            return False
        
        if self.state == CircuitState.HALF_OPEN:
            return True
        
        return False
    
    def time_until_retry(self) -> Optional[int]:
        """Retourne le temps restant avant retry (en secondes)"""
        if self.state != CircuitState.OPEN or not self.blocked_until:
            return None
        
        now = datetime.now(timezone.utc)
        if now >= self.blocked_until:
            return 0
        
        return int((self.blocked_until - now).total_seconds())


class MultiSourceRateLimiter:
    """
    Rate limiter et circuit breaker pour plusieurs sources.
    Thread-safe avec asyncio.Lock.
    """
    
    def __init__(self):
        self._sources: dict[str, SourceState] = {}
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        
        # Config par défaut par source
        self._config = {
            "autoscout24": {"min_delay": 1.5, "jitter": 0.5, "failure_threshold": 3},
            "lacentrale": {"min_delay": 2.0, "jitter": 0.8, "failure_threshold": 3},
            "paruvendu": {"min_delay": 1.5, "jitter": 0.5, "failure_threshold": 3},
            "leboncoin": {"min_delay": 3.0, "jitter": 1.0, "failure_threshold": 2},
            "marketplace": {"min_delay": 5.0, "jitter": 2.0, "failure_threshold": 2},
        }
    
    def _get_source_state(self, source: str) -> SourceState:
        """Récupère ou crée l'état d'une source"""
        if source not in self._sources:
            config = self._config.get(source, {})
            self._sources[source] = SourceState(
                name=source,
                failure_threshold=config.get("failure_threshold", 3),
                recovery_timeout_sec=config.get("recovery_timeout", 120),
            )
        return self._sources[source]
    
    def _get_lock(self, source: str) -> asyncio.Lock:
        """Récupère ou crée le lock d'une source"""
        if source not in self._locks:
            self._locks[source] = asyncio.Lock()
        return self._locks[source]
    
    async def wait_for_slot(self, source: str) -> bool:
        """
        Attend le prochain slot disponible pour une source.
        
        Returns:
            True si on peut exécuter, False si source bloquée
        """
        state = self._get_source_state(source)
        
        if not state.can_execute():
            remaining = state.time_until_retry()
            print(f"⏸️ {source}: blocked, retry in {remaining}s")
            return False
        
        lock = self._get_lock(source)
        async with lock:
            config = self._config.get(source, {"min_delay": 1.5, "jitter": 0.5})
            min_delay = config["min_delay"]
            jitter = config["jitter"]
            
            now = asyncio.get_event_loop().time()
            last = self._last_request.get(source, 0)
            elapsed = now - last
            
            # Calculer le délai avec jitter
            required_delay = min_delay + random.uniform(-jitter, jitter)
            
            if elapsed < required_delay:
                wait_time = required_delay - elapsed
                await asyncio.sleep(wait_time)
            
            self._last_request[source] = asyncio.get_event_loop().time()
        
        return True
    
    def record_success(self, source: str):
        """Enregistre un succès pour une source"""
        state = self._get_source_state(source)
        state.record_success()
    
    def record_failure(self, source: str, is_block: bool = False):
        """Enregistre un échec pour une source"""
        state = self._get_source_state(source)
        state.record_failure(is_block=is_block)
    
    def is_blocked(self, source: str) -> bool:
        """Vérifie si une source est bloquée"""
        state = self._get_source_state(source)
        return not state.can_execute()
    
    def get_status(self) -> dict[str, dict]:
        """Retourne le statut de toutes les sources"""
        return {
            name: {
                "state": state.state.value,
                "failures": state.failure_count,
                "blocked_until": state.blocked_until.isoformat() if state.blocked_until else None,
                "consecutive_blocks": state.consecutive_blocks,
            }
            for name, state in self._sources.items()
        }


# Instance globale
_rate_limiter: Optional[MultiSourceRateLimiter] = None


def get_rate_limiter() -> MultiSourceRateLimiter:
    """Retourne l'instance du rate limiter"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = MultiSourceRateLimiter()
    return _rate_limiter
