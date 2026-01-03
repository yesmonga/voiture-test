"""
HTTP Client - Client HTTP avec rate limiting et circuit breaker
Respecte les limites par site et gère les erreurs proprement
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from config.settings import CONFIG_DIR, get_settings


def load_sites_config() -> dict[str, Any]:
    """Charge la config des sites"""
    path = CONFIG_DIR / "sites.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@dataclass
class RateLimiter:
    """Token bucket rate limiter"""
    
    requests_per_minute: int = 10
    min_delay: float = 2.0
    max_delay: float = 5.0
    jitter: bool = True
    
    # État interne
    _tokens: float = field(default=10.0, init=False)
    _last_update: float = field(default_factory=time.time, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    def __post_init__(self):
        self._tokens = float(self.requests_per_minute)
    
    async def acquire(self) -> float:
        """
        Attend d'avoir un token disponible.
        Retourne le délai attendu.
        """
        async with self._lock:
            now = time.time()
            
            # Regénérer les tokens
            elapsed = now - self._last_update
            self._tokens = min(
                self.requests_per_minute,
                self._tokens + elapsed * (self.requests_per_minute / 60.0)
            )
            self._last_update = now
            
            # Si pas de token, attendre
            if self._tokens < 1:
                wait_time = (1 - self._tokens) * (60.0 / self.requests_per_minute)
                await asyncio.sleep(wait_time)
                self._tokens = 1
            
            # Consommer un token
            self._tokens -= 1
            
            # Délai avec jitter
            delay = random.uniform(self.min_delay, self.max_delay) if self.jitter else self.min_delay
            await asyncio.sleep(delay)
            
            return delay


@dataclass
class CircuitBreaker:
    """Circuit breaker pour éviter de surcharger un site en erreur"""
    
    error_threshold: int = 5
    window_seconds: int = 300
    cooldown_seconds: int = 600
    
    # État interne
    _errors: list[float] = field(default_factory=list, init=False)
    _open_until: Optional[float] = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    @property
    def is_open(self) -> bool:
        """Vérifie si le circuit est ouvert (en pause)"""
        if self._open_until is None:
            return False
        return time.time() < self._open_until
    
    async def record_success(self):
        """Enregistre un succès"""
        async with self._lock:
            # Reset après succès si circuit fermé
            if not self.is_open:
                self._errors.clear()
    
    async def record_error(self) -> bool:
        """
        Enregistre une erreur.
        Retourne True si le circuit s'ouvre.
        """
        async with self._lock:
            now = time.time()
            
            # Nettoyer les erreurs anciennes
            cutoff = now - self.window_seconds
            self._errors = [e for e in self._errors if e > cutoff]
            
            # Ajouter l'erreur
            self._errors.append(now)
            
            # Vérifier le seuil
            if len(self._errors) >= self.error_threshold:
                self._open_until = now + self.cooldown_seconds
                self._errors.clear()
                return True
            
            return False
    
    def time_until_close(self) -> float:
        """Retourne le temps restant avant fermeture du circuit"""
        if self._open_until is None:
            return 0
        remaining = self._open_until - time.time()
        return max(0, remaining)


class SiteClient:
    """Client HTTP pour un site spécifique avec rate limiting"""
    
    def __init__(self, site_id: str, config: dict[str, Any]):
        self.site_id = site_id
        self.config = config
        self.name = config.get("name", site_id)
        self.base_url = config.get("base_url", "")
        self.enabled = config.get("enabled", True)
        
        # Rate limiting
        rate_config = config.get("rate_limit", {})
        self.rate_limiter = RateLimiter(
            requests_per_minute=rate_config.get("requests_per_minute", 10),
            min_delay=rate_config.get("min_delay_seconds", 2.0),
            max_delay=rate_config.get("max_delay_seconds", 5.0),
            jitter=rate_config.get("jitter", True)
        )
        
        # Circuit breaker
        cb_config = config.get("circuit_breaker", {})
        self.circuit_breaker = CircuitBreaker(
            error_threshold=cb_config.get("error_threshold", 5),
            window_seconds=cb_config.get("window_seconds", 300),
            cooldown_seconds=cb_config.get("cooldown_seconds", 600)
        )
        
        # Headers
        self.headers = config.get("headers", {})
        
        # Stats
        self.requests_count = 0
        self.errors_count = 0
        self.last_request: Optional[datetime] = None
    
    def is_available(self) -> bool:
        """Vérifie si le site est disponible"""
        return self.enabled and not self.circuit_breaker.is_open


class HttpClientManager:
    """
    Gestionnaire de clients HTTP avec rate limiting par site.
    Usage personnel, respecte les limites configurées.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.sites_config = load_sites_config()
        self.http_config = self.sites_config.get("http", {})
        
        # Clients par site
        self.site_clients: dict[str, SiteClient] = {}
        self._init_site_clients()
        
        # User-agents
        self.user_agents = self.http_config.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ])
        
        # Proxies
        self.proxies: list[str] = []
        self._proxy_index = 0
        
        # Client httpx partagé
        self._client: Optional[httpx.AsyncClient] = None
    
    def _init_site_clients(self):
        """Initialise les clients pour chaque site"""
        sites = self.sites_config.get("sites", {})
        for site_id, site_config in sites.items():
            self.site_clients[site_id] = SiteClient(site_id, site_config)
    
    def set_proxies(self, proxies: list[str]):
        """Configure les proxies"""
        self.proxies = proxies
    
    def get_proxy(self) -> Optional[str]:
        """Retourne un proxy en rotation"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self._proxy_index % len(self.proxies)]
        self._proxy_index += 1
        return proxy
    
    def get_random_user_agent(self) -> str:
        """Retourne un User-Agent aléatoire"""
        return random.choice(self.user_agents)
    
    def get_headers(self, site_id: Optional[str] = None) -> dict[str, str]:
        """Retourne les headers pour une requête"""
        default_headers = self.http_config.get("default_headers", {}).copy()
        default_headers["User-Agent"] = self.get_random_user_agent()
        
        if site_id and site_id in self.site_clients:
            site_headers = self.site_clients[site_id].headers
            default_headers.update(site_headers)
        
        return default_headers
    
    async def get_client(self) -> httpx.AsyncClient:
        """Retourne le client httpx (lazy init)"""
        if self._client is None or self._client.is_closed:
            proxy = self.get_proxy()
            timeout = httpx.Timeout(
                connect=self.http_config.get("connect_timeout", 10),
                read=self.http_config.get("read_timeout", 30),
                write=30,
                pool=30
            )
            
            self._client = httpx.AsyncClient(
                proxy=proxy,
                timeout=timeout,
                follow_redirects=True,
                http2=True
            )
        
        return self._client
    
    async def close(self):
        """Ferme le client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def fetch(
        self,
        url: str,
        site_id: str,
        method: str = "GET",
        **kwargs
    ) -> Optional[httpx.Response]:
        """
        Effectue une requête HTTP avec rate limiting.
        
        Args:
            url: URL à requêter
            site_id: ID du site (pour rate limiting)
            method: Méthode HTTP
            **kwargs: Arguments passés à httpx
        
        Returns:
            Response ou None si erreur/circuit ouvert
        """
        # Vérifier la disponibilité du site
        if site_id not in self.site_clients:
            print(f"⚠️ Site inconnu: {site_id}")
            return None
        
        site_client = self.site_clients[site_id]
        
        if not site_client.is_available():
            remaining = site_client.circuit_breaker.time_until_close()
            print(f"⏸️ {site_client.name} en pause ({int(remaining)}s restants)")
            return None
        
        # Rate limiting
        await site_client.rate_limiter.acquire()
        
        # Préparer les headers
        headers = kwargs.pop("headers", {})
        headers.update(self.get_headers(site_id))
        
        # Effectuer la requête
        try:
            client = await self.get_client()
            
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )
            
            # Mettre à jour les stats
            site_client.requests_count += 1
            site_client.last_request = datetime.now(timezone.utc)
            
            # Vérifier le statut
            if response.status_code >= 400:
                site_client.errors_count += 1
                opened = await site_client.circuit_breaker.record_error()
                if opened:
                    print(f"🔴 Circuit ouvert pour {site_client.name}")
                return None
            
            await site_client.circuit_breaker.record_success()
            return response
            
        except httpx.HTTPError as e:
            site_client.errors_count += 1
            opened = await site_client.circuit_breaker.record_error()
            if opened:
                print(f"🔴 Circuit ouvert pour {site_client.name}: {e}")
            return None
        except Exception as e:
            print(f"❌ Erreur HTTP {site_id}: {e}")
            return None
    
    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Retourne les statistiques par site"""
        stats = {}
        for site_id, client in self.site_clients.items():
            stats[site_id] = {
                "name": client.name,
                "enabled": client.enabled,
                "available": client.is_available(),
                "requests": client.requests_count,
                "errors": client.errors_count,
                "last_request": client.last_request.isoformat() if client.last_request else None,
                "circuit_open": client.circuit_breaker.is_open,
                "cooldown_remaining": int(client.circuit_breaker.time_until_close())
            }
        return stats


# Instance globale
_http_manager: Optional[HttpClientManager] = None


def get_http_manager() -> HttpClientManager:
    """Retourne l'instance du gestionnaire HTTP"""
    global _http_manager
    if _http_manager is None:
        _http_manager = HttpClientManager()
    return _http_manager
