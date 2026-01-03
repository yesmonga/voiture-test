"""
Base Scraper - Classe abstraite pour tous les scrapers
"""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict, Any
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from models.annonce import Annonce
from models.database import get_db
from utils.anti_bot import AntiBotManager, anti_bot
from utils.logger import get_logger, log_scraping_start, log_scraping_end, log_error
from config import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY, VEHICULES_CIBLES, TOUS_DEPARTEMENTS

logger = get_logger(__name__)


class BaseScraper(ABC):
    """Classe de base pour les scrapers de sites d'annonces"""
    
    name: str = "base"
    base_url: str = ""
    
    def __init__(self):
        self.anti_bot = anti_bot
        self.db = get_db()
        self.session: Optional[httpx.AsyncClient] = None
        self.last_scrape_time: Optional[datetime] = None
        self.annonces_trouvees: List[Annonce] = []
    
    async def __aenter__(self):
        await self.init_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_session()
    
    async def init_session(self):
        """Initialise la session HTTP"""
        proxy = self.anti_bot.get_proxy()
        self.session = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers=self.anti_bot.get_headers(),
            proxy=proxy  # httpx 0.28+ uses 'proxy' instead of 'proxies'
        )
    
    async def close_session(self):
        """Ferme la session HTTP"""
        if self.session:
            await self.session.aclose()
            self.session = None
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def fetch_page(self, url: str, headers: Dict = None) -> Optional[str]:
        """Récupère le contenu d'une page avec retry"""
        try:
            if not self.session:
                await self.init_session()
            
            # Headers avec rotation
            request_headers = self.anti_bot.get_headers(referer=self.base_url)
            if headers:
                request_headers.update(headers)
            
            response = await self.session.get(url, headers=request_headers)
            response.raise_for_status()
            
            # Délai anti-bot
            await self.anti_bot.async_random_delay(1.5, 3.0)
            
            return response.text
            
        except httpx.HTTPStatusError as e:
            log_error(f"Erreur HTTP {e.response.status_code} pour {url}", e)
            raise
        except Exception as e:
            log_error(f"Erreur lors de la récupération de {url}", e)
            raise
    
    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse le HTML avec BeautifulSoup"""
        return BeautifulSoup(html, "lxml")
    
    @abstractmethod
    async def build_search_url(self, vehicule_config: Dict, page: int = 1) -> str:
        """Construit l'URL de recherche pour un véhicule cible"""
        pass
    
    @abstractmethod
    async def parse_listing_page(self, html: str) -> List[Dict[str, Any]]:
        """Parse une page de résultats et retourne les données brutes des annonces"""
        pass
    
    @abstractmethod
    async def parse_annonce_detail(self, url: str, data: Dict = None) -> Optional[Annonce]:
        """Parse le détail d'une annonce et retourne un objet Annonce"""
        pass
    
    def is_new_annonce(self, url: str) -> bool:
        """Vérifie si l'annonce est nouvelle"""
        return not self.db.exists(url)
    
    def clean_price(self, price_str: str) -> Optional[int]:
        """Nettoie et convertit un prix en entier"""
        if not price_str:
            return None
        
        # Supprimer tout sauf les chiffres
        cleaned = "".join(c for c in price_str if c.isdigit())
        
        try:
            return int(cleaned) if cleaned else None
        except ValueError:
            return None
    
    def clean_km(self, km_str: str) -> Optional[int]:
        """Nettoie et convertit un kilométrage en entier"""
        if not km_str:
            return None
        
        # Supprimer tout sauf les chiffres
        cleaned = "".join(c for c in km_str if c.isdigit())
        
        try:
            return int(cleaned) if cleaned else None
        except ValueError:
            return None
    
    def clean_year(self, year_str: str) -> Optional[int]:
        """Nettoie et convertit une année en entier"""
        if not year_str:
            return None
        
        # Chercher un nombre de 4 chiffres commençant par 19 ou 20
        import re
        match = re.search(r"(19|20)\d{2}", str(year_str))
        if match:
            return int(match.group())
        return None
    
    def extract_departement(self, location: str, code_postal: str = None) -> Optional[str]:
        """Extrait le département depuis la localisation ou le code postal"""
        if code_postal and len(code_postal) >= 2:
            return code_postal[:2]
        
        if location:
            import re
            # Chercher un code postal dans le texte
            match = re.search(r"\b(\d{5})\b", location)
            if match:
                return match.group()[:2]
            
            # Chercher un département entre parenthèses (ex: "Créteil (94)")
            match = re.search(r"\((\d{2,3})\)", location)
            if match:
                dept = match.group(1)
                return dept[:2] if len(dept) > 2 else dept
        
        return None
    
    def is_in_target_zone(self, departement: str) -> bool:
        """Vérifie si le département est dans la zone cible"""
        if not departement:
            return True  # On garde si on ne peut pas déterminer
        return departement in TOUS_DEPARTEMENTS
    
    def matches_vehicle_criteria(self, annonce_data: Dict, vehicule_config: Dict) -> bool:
        """Vérifie si une annonce correspond aux critères d'un véhicule cible"""
        # Vérification du prix
        prix = annonce_data.get("prix")
        if prix:
            if prix < vehicule_config.get("prix_min", 0):
                return False
            if prix > vehicule_config.get("prix_max", 999999):
                return False
        
        # Vérification du kilométrage
        km = annonce_data.get("kilometrage")
        if km:
            if km < vehicule_config.get("km_min", 0):
                return False
            if km > vehicule_config.get("km_max", 999999):
                return False
        
        # Vérification de l'année
        annee = annonce_data.get("annee")
        if annee:
            if annee < vehicule_config.get("annee_min", 1990):
                return False
            if annee > vehicule_config.get("annee_max", 2025):
                return False
        
        # Vérification du carburant
        carburant_config = vehicule_config.get("carburant")
        carburant_annonce = annonce_data.get("carburant") or ""
        if isinstance(carburant_annonce, str):
            carburant_annonce = carburant_annonce.lower()
        else:
            carburant_annonce = ""
        if carburant_config and carburant_annonce:
            if carburant_config.lower() not in carburant_annonce:
                return False
        
        # Vérification des motorisations à exclure
        titre = (annonce_data.get("titre") or "").lower()
        description = (annonce_data.get("description") or "").lower()
        motorisation = (annonce_data.get("motorisation") or "").lower()
        texte_complet = f"{titre} {description} {motorisation}"
        
        for exclu in vehicule_config.get("motorisation_exclude", []):
            if exclu.lower() in texte_complet:
                return False
        
        return True
    
    async def scrape_vehicule(self, vehicule_id: str, vehicule_config: Dict) -> List[Annonce]:
        """Scrape les annonces pour un véhicule cible spécifique"""
        annonces = []
        page = 1
        max_pages = 5  # Limiter le nombre de pages
        
        while page <= max_pages:
            try:
                url = await self.build_search_url(vehicule_config, page)
                html = await self.fetch_page(url)
                
                if not html:
                    break
                
                listings = await self.parse_listing_page(html)
                
                if not listings:
                    break
                
                for listing_data in listings:
                    # Vérifier si c'est une nouvelle annonce
                    annonce_url = listing_data.get("url")
                    if not annonce_url or not self.is_new_annonce(annonce_url):
                        continue
                    
                    # Vérifier la zone géographique
                    dept = self.extract_departement(
                        listing_data.get("ville"),
                        listing_data.get("code_postal")
                    )
                    if not self.is_in_target_zone(dept):
                        continue
                    
                    # Vérifier les critères du véhicule
                    if not self.matches_vehicle_criteria(listing_data, vehicule_config):
                        continue
                    
                    # Parser le détail si nécessaire
                    try:
                        annonce = await self.parse_annonce_detail(annonce_url, listing_data)
                        if annonce:
                            annonce.vehicule_cible_id = vehicule_id
                            annonces.append(annonce)
                    except Exception as e:
                        log_error(f"Erreur parsing détail {annonce_url}", e)
                        continue
                
                page += 1
                
            except Exception as e:
                log_error(f"Erreur scraping page {page} pour {vehicule_id}", e)
                break
        
        return annonces
    
    async def scrape_all(self) -> List[Annonce]:
        """Scrape toutes les annonces pour tous les véhicules cibles"""
        log_scraping_start(self.name)
        
        all_annonces = []
        new_count = 0
        
        async with self:
            for vehicule_id, vehicule_config in VEHICULES_CIBLES.items():
                try:
                    logger.debug(f"Scraping {vehicule_id} sur {self.name}...")
                    annonces = await self.scrape_vehicule(vehicule_id, vehicule_config)
                    
                    for annonce in annonces:
                        # Sauvegarder en base
                        is_new = self.db.save_annonce(annonce)
                        if is_new:
                            new_count += 1
                        all_annonces.append(annonce)
                    
                    # Délai entre chaque recherche de véhicule
                    await self.anti_bot.async_random_delay(2.0, 4.0)
                    
                except Exception as e:
                    log_error(f"Erreur scraping {vehicule_id} sur {self.name}", e)
                    continue
        
        self.last_scrape_time = datetime.now()
        self.annonces_trouvees = all_annonces
        
        log_scraping_end(self.name, len(all_annonces), new_count)
        
        return all_annonces
    
    def run(self) -> List[Annonce]:
        """Point d'entrée synchrone pour le scraping"""
        return asyncio.run(self.scrape_all())
