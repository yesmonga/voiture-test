"""
HTTP Client Commun - Anti-bot robuste pour tous les scrapers
- User-Agent rotation réaliste
- Headers cohérents par source
- Timeout, retry, backoff exponentiel
- Détection blocage (403/429/captcha)
"""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from enum import Enum

import httpx

from scrapers.rate_limiter import get_rate_limiter


# User-Agents réalistes (Chrome/Firefox/Safari récents)
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Firefox Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

# Headers de base par type de requête
BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}

# Referers par source
REFERERS = {
    "autoscout24": "https://www.autoscout24.fr/",
    "lacentrale": "https://www.lacentrale.fr/",
    "paruvendu": "https://www.paruvendu.fr/",
    "leboncoin": "https://www.leboncoin.fr/",
}


class FetchResult(Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"  # 403, 429
    NOT_FOUND = "not_found"  # 404
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"  # Circuit breaker


@dataclass
class HttpResponse:
    """Résultat d'une requête HTTP"""
    status: FetchResult
    status_code: int
    html: str
    url: str
    latency_ms: int
    error: Optional[str] = None


class RobustHttpClient:
    """
    Client HTTP robuste avec anti-bot intégré.
    Utilisé par tous les scrapers.
    """
    
    def __init__(
        self,
        source: str,
        timeout: float = 30.0,
        max_retries: int = 2,
        base_delay: float = 1.0,
    ):
        self.source = source.lower()
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay
        
        self._client: Optional[httpx.AsyncClient] = None
        self._ua_index = random.randint(0, len(USER_AGENTS) - 1)
        self._rate_limiter = get_rate_limiter()
        
        # Stats
        self.requests_made = 0
        self.requests_success = 0
        self.requests_blocked = 0
        self.total_latency_ms = 0
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy init du client avec cookies persistants"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                http2=True,  # HTTP/2 pour ressembler à un vrai navigateur
            )
        return self._client
    
    async def close(self):
        """Ferme le client"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _get_headers(self, referer: Optional[str] = None) -> dict[str, str]:
        """Génère des headers réalistes avec rotation UA"""
        self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
        
        headers = BASE_HEADERS.copy()
        headers["User-Agent"] = USER_AGENTS[self._ua_index]
        
        # Referer
        if referer:
            headers["Referer"] = referer
        elif self.source in REFERERS:
            headers["Referer"] = REFERERS[self.source]
        
        return headers
    
    def _detect_block(self, status_code: int, html: str) -> bool:
        """Détecte si on est bloqué - moins agressif"""
        if status_code in (403, 429, 503):
            return True
        
        # Ne pas détecter comme blocage si la page contient du contenu valide
        html_lower = html.lower()
        
        # Indicateurs de contenu valide
        valid_indicators = ["annonce", "voiture", "prix", "€", "listing", "vehicle"]
        has_valid_content = any(ind in html_lower for ind in valid_indicators)
        
        if has_valid_content and len(html) > 10000:
            return False  # Page avec contenu valide
        
        # Détection captcha/challenge seulement si pas de contenu valide
        block_patterns = [
            "captcha",
            "access denied",
            "blocked",
            "too many requests",
            "rate limit",
        ]
        
        # Doit avoir un pattern de blocage ET peu de contenu
        has_block_pattern = any(pattern in html_lower for pattern in block_patterns)
        return has_block_pattern and len(html) < 50000
    
    async def fetch(
        self,
        url: str,
        referer: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ) -> HttpResponse:
        """
        Fetch une URL avec gestion anti-bot complète.
        """
        # Vérifier circuit breaker
        can_proceed = await self._rate_limiter.wait_for_slot(self.source)
        if not can_proceed:
            return HttpResponse(
                status=FetchResult.RATE_LIMITED,
                status_code=0,
                html="",
                url=url,
                latency_ms=0,
                error="Circuit breaker active",
            )
        
        self.requests_made += 1
        start_time = datetime.now(timezone.utc)
        
        headers = self._get_headers(referer)
        if extra_headers:
            headers.update(extra_headers)
        
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.get(url, headers=headers)
                
                latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                self.total_latency_ms += latency_ms
                
                html = response.text
                status_code = response.status_code
                
                # Vérifier blocage
                if self._detect_block(status_code, html):
                    self._rate_limiter.record_failure(self.source, is_block=True)
                    self.requests_blocked += 1
                    
                    return HttpResponse(
                        status=FetchResult.BLOCKED,
                        status_code=status_code,
                        html=html,
                        url=url,
                        latency_ms=latency_ms,
                        error=f"Blocked (status={status_code})",
                    )
                
                # 404
                if status_code == 404:
                    return HttpResponse(
                        status=FetchResult.NOT_FOUND,
                        status_code=status_code,
                        html=html,
                        url=url,
                        latency_ms=latency_ms,
                    )
                
                # Succès
                if status_code == 200:
                    self._rate_limiter.record_success(self.source)
                    self.requests_success += 1
                    
                    return HttpResponse(
                        status=FetchResult.SUCCESS,
                        status_code=status_code,
                        html=html,
                        url=url,
                        latency_ms=latency_ms,
                    )
                
                # Autre status
                self._rate_limiter.record_failure(self.source)
                return HttpResponse(
                    status=FetchResult.ERROR,
                    status_code=status_code,
                    html=html,
                    url=url,
                    latency_ms=latency_ms,
                    error=f"Unexpected status: {status_code}",
                )
                
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                last_error = str(e)
                self._rate_limiter.record_failure(self.source)
                break
        
        # Échec après retries
        latency_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        return HttpResponse(
            status=FetchResult.ERROR if "Timeout" not in (last_error or "") else FetchResult.TIMEOUT,
            status_code=0,
            html="",
            url=url,
            latency_ms=latency_ms,
            error=last_error,
        )
    
    def get_stats(self) -> dict:
        """Retourne les stats du client"""
        avg_latency = self.total_latency_ms / max(self.requests_made, 1)
        return {
            "source": self.source,
            "requests": self.requests_made,
            "success": self.requests_success,
            "blocked": self.requests_blocked,
            "avg_latency_ms": int(avg_latency),
        }


# Cache des clients par source
_clients: dict[str, RobustHttpClient] = {}


def get_http_client(source: str) -> RobustHttpClient:
    """Retourne un client HTTP pour une source (singleton par source)"""
    source_lower = source.lower()
    if source_lower not in _clients:
        _clients[source_lower] = RobustHttpClient(source_lower)
    return _clients[source_lower]


async def close_all_clients():
    """Ferme tous les clients"""
    for client in _clients.values():
        await client.close()
    _clients.clear()
