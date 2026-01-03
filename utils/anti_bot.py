"""
Anti-Bot Manager - Gestion des techniques anti-détection
"""

import random
import time
import asyncio
from typing import Optional, Dict, List
from fake_useragent import UserAgent

from config import PROXY_URL, REQUEST_TIMEOUT


class AntiBotManager:
    """Gestionnaire des techniques anti-bot"""
    
    # User agents réalistes
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]
    
    # Headers HTTP réalistes
    BASE_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    
    def __init__(self, proxies: List[str] = None):
        self.proxies = proxies or []
        if PROXY_URL:
            self.proxies.append(PROXY_URL)
        
        self.current_proxy_index = 0
        
        # Essayer d'utiliser fake_useragent pour plus de diversité
        try:
            self.ua = UserAgent()
        except Exception:
            self.ua = None
    
    def get_random_user_agent(self) -> str:
        """Retourne un User-Agent aléatoire"""
        if self.ua:
            try:
                return self.ua.random
            except Exception:
                pass
        return random.choice(self.USER_AGENTS)
    
    def get_headers(self, referer: str = None) -> Dict[str, str]:
        """Retourne des headers HTTP avec User-Agent aléatoire"""
        headers = self.BASE_HEADERS.copy()
        headers["User-Agent"] = self.get_random_user_agent()
        
        if referer:
            headers["Referer"] = referer
        
        return headers
    
    def get_proxy(self) -> Optional[str]:
        """Retourne un proxy de la liste (rotation)"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    def get_proxy_dict(self) -> Optional[Dict[str, str]]:
        """Retourne un dictionnaire proxy pour httpx/requests"""
        proxy = self.get_proxy()
        if proxy:
            return {
                "http://": proxy,
                "https://": proxy
            }
        return None
    
    @staticmethod
    def random_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Pause aléatoire entre les requêtes"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)
    
    @staticmethod
    async def async_random_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Pause aléatoire asynchrone"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)
    
    @staticmethod
    def jitter_interval(base_interval: int, jitter_percent: float = 0.2) -> int:
        """Ajoute une variation aléatoire à un intervalle"""
        jitter = base_interval * jitter_percent
        return int(base_interval + random.uniform(-jitter, jitter))
    
    def get_playwright_context_options(self) -> Dict:
        """Options pour créer un contexte Playwright anti-détection"""
        return {
            "user_agent": self.get_random_user_agent(),
            "viewport": {"width": random.randint(1200, 1920), "height": random.randint(800, 1080)},
            "locale": "fr-FR",
            "timezone_id": "Europe/Paris",
            "geolocation": {"longitude": 2.3522, "latitude": 48.8566},  # Paris
            "permissions": ["geolocation"],
            "color_scheme": random.choice(["light", "dark"]),
            "java_script_enabled": True,
            "accept_downloads": False,
            "extra_http_headers": {
                "Accept-Language": "fr-FR,fr;q=0.9",
            }
        }
    
    @staticmethod
    def simulate_human_scroll(page) -> None:
        """Simule un scroll humain sur une page Playwright"""
        import random
        
        # Scroll progressif vers le bas
        for _ in range(random.randint(2, 5)):
            scroll_amount = random.randint(200, 500)
            page.mouse.wheel(0, scroll_amount)
            time.sleep(random.uniform(0.3, 0.8))
        
        # Parfois remonter un peu
        if random.random() > 0.7:
            page.mouse.wheel(0, -random.randint(100, 200))
            time.sleep(random.uniform(0.2, 0.5))
    
    @staticmethod
    def simulate_human_mouse_movement(page) -> None:
        """Simule des mouvements de souris humains"""
        import random
        
        viewport = page.viewport_size
        if not viewport:
            return
        
        # Quelques mouvements aléatoires
        for _ in range(random.randint(2, 4)):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.1, 0.3))


# Proxies résidentiels FR
RESIDENTIAL_PROXIES = [
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-geoebxsw-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-ixifzhpz-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-qcz7n3e0-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-3o2i3j57-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-fx2fsyou-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-6e0vupyv-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-lmwa9c0b-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-pepds97q-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-jqu420pj-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-w3yficdr-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-3thix74o-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-5taufkvt-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-pk824rfm-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-o6prx5pe-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-ars5zlem-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-r8szkvj3-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-mjc4z0bs-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-6xdxd0at-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-5oxmvv7h-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-z1y8y1xp-duration-60@resi.thexyzstore.com:8000",
]

# Instance globale avec proxies
anti_bot = AntiBotManager(proxies=RESIDENTIAL_PROXIES)
