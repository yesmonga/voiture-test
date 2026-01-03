"""
LeBoncoin Scraper avec Playwright - Contourne la protection anti-bot
"""

import re
import json
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup

from models.annonce import Annonce
from models.database import get_db
from utils.anti_bot import anti_bot
from utils.logger import get_logger, log_scraping_start, log_scraping_end, log_error
from config import VEHICULES_CIBLES, TOUS_DEPARTEMENTS

logger = get_logger(__name__)


class LeBoncoinPlaywrightScraper:
    """Scraper LeBoncoin utilisant Playwright pour contourner l'anti-bot"""
    
    name = "leboncoin"
    base_url = "https://www.leboncoin.fr"
    
    def __init__(self):
        self.db = get_db()
        self.browser: Optional[Browser] = None
        self.annonces_trouvees: List[Annonce] = []
    
    async def init_browser(self):
        """Initialise le navigateur Playwright avec proxy"""
        self.playwright = await async_playwright().start()
        
        # Récupérer un proxy
        proxy_url = anti_bot.get_proxy()
        proxy_config = None
        
        if proxy_url:
            # Parser le proxy: http://user:pass@host:port
            import re
            match = re.match(r'http://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
            if match:
                proxy_config = {
                    "server": f"http://{match.group(3)}:{match.group(4)}",
                    "username": match.group(1),
                    "password": match.group(2)
                }
                logger.info(f"🔄 Proxy configuré: {match.group(3)}:{match.group(4)}")
        
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ],
            proxy=proxy_config
        )
    
    async def close_browser(self):
        """Ferme le navigateur"""
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright') and self.playwright:
            await self.playwright.stop()
    
    async def get_page(self) -> Page:
        """Crée une nouvelle page avec les options anti-détection"""
        context = await self.browser.new_context(
            **anti_bot.get_playwright_context_options()
        )
        page = await context.new_page()
        
        # Masquer webdriver
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)
        
        return page
    
    def build_search_url(self, vehicule_config: Dict, page_num: int = 1) -> str:
        """Construit l'URL de recherche LeBoncoin"""
        marque = vehicule_config.get("marque", "").lower()
        modeles = vehicule_config.get("modele", [])
        modele = modeles[0].lower() if modeles else ""
        
        params = {
            "category": "2",
            "owner_type": "private",
            "sort": "time",
            "order": "desc",
            "locations": "r_12",  # Île-de-France
        }
        
        if vehicule_config.get("prix_min"):
            params["price"] = f"{vehicule_config['prix_min']}-{vehicule_config.get('prix_max', '')}"
        
        if vehicule_config.get("km_max"):
            params["mileage"] = f"{vehicule_config.get('km_min', 0)}-{vehicule_config['km_max']}"
        
        if vehicule_config.get("annee_min"):
            params["regdate"] = f"{vehicule_config['annee_min']}-{vehicule_config.get('annee_max', 2025)}"
        
        carburant = vehicule_config.get("carburant")
        if carburant:
            params["fuel"] = "2" if carburant.lower() == "diesel" else "1"
        
        if marque:
            params["brand"] = marque
        if modele:
            params["model"] = modele
        
        if page_num > 1:
            params["page"] = str(page_num)
        
        return f"{self.base_url}/recherche?{urlencode(params)}"
    
    async def scrape_page(self, page: Page, url: str) -> List[Dict]:
        """Scrape une page de résultats"""
        listings = []
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)  # Attendre le chargement JS
            
            # Accepter les cookies si présent
            try:
                cookie_btn = page.locator('button:has-text("Accepter")')
                if await cookie_btn.count() > 0:
                    await cookie_btn.first.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            
            # Récupérer le contenu de la page
            content = await page.content()
            soup = BeautifulSoup(content, "lxml")
            
            # Chercher les données JSON dans la page
            scripts = soup.find_all("script")
            for script in scripts:
                if script.string and ("ads" in script.string or "listItems" in script.string):
                    try:
                        # Chercher les patterns JSON
                        matches = re.findall(r'\{[^{}]*"list_id"[^{}]*\}', script.string)
                        for match in matches:
                            try:
                                ad = json.loads(match)
                                listing = self._parse_ad(ad)
                                if listing:
                                    listings.append(listing)
                            except json.JSONDecodeError:
                                continue
                    except Exception:
                        continue
            
            # Parser le HTML directement si pas de JSON
            if not listings:
                listings = self._parse_html(soup)
                
        except Exception as e:
            log_error(f"Erreur scraping page LeBoncoin: {url}", e)
        
        return listings
    
    def _parse_ad(self, ad: Dict) -> Optional[Dict]:
        """Parse une annonce depuis JSON"""
        try:
            list_id = ad.get("list_id")
            if not list_id:
                return None
            
            url = f"{self.base_url}/ad/voitures/{list_id}.htm"
            attributes = {attr.get("key"): attr.get("value") for attr in ad.get("attributes", []) if isinstance(attr, dict)}
            location = ad.get("location", {}) if isinstance(ad.get("location"), dict) else {}
            
            prix = ad.get("price")
            if isinstance(prix, list):
                prix = prix[0] if prix else None
            
            return {
                "url": url,
                "source": self.name,
                "titre": ad.get("subject"),
                "prix": prix,
                "ville": location.get("city"),
                "code_postal": location.get("zipcode"),
                "departement": location.get("department_id"),
                "marque": attributes.get("brand"),
                "modele": attributes.get("model"),
                "annee": self._clean_year(attributes.get("regdate")),
                "kilometrage": self._clean_km(attributes.get("mileage")),
                "carburant": attributes.get("fuel"),
                "type_vendeur": "particulier" if ad.get("owner_type") == "private" else "pro",
            }
        except Exception:
            return None
    
    def _parse_html(self, soup) -> List[Dict]:
        """Parse les annonces depuis le HTML"""
        listings = []
        
        cards = soup.select("a[data-qa-id='aditem_container']") or \
                soup.select("[data-test-id='ad']") or \
                soup.select("article a[href*='/ad/']")
        
        for card in cards[:20]:  # Limiter
            try:
                href = card.get("href", "")
                if not href or "/ad/" not in href:
                    continue
                
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                title_elem = card.select_one("[data-qa-id='aditem_title']") or card.find("p", class_=re.compile(r"title", re.I))
                titre = title_elem.get_text(strip=True) if title_elem else None
                
                price_elem = card.select_one("[data-qa-id='aditem_price']") or card.find(class_=re.compile(r"price", re.I))
                prix = self._clean_price(price_elem.get_text()) if price_elem else None
                
                loc_elem = card.select_one("[data-qa-id='aditem_location']")
                ville = loc_elem.get_text(strip=True) if loc_elem else None
                
                listings.append({
                    "url": url,
                    "source": self.name,
                    "titre": titre,
                    "prix": prix,
                    "ville": ville,
                })
            except Exception:
                continue
        
        return listings
    
    def _clean_price(self, s: str) -> Optional[int]:
        if not s:
            return None
        cleaned = "".join(c for c in s if c.isdigit())
        return int(cleaned) if cleaned else None
    
    def _clean_km(self, s) -> Optional[int]:
        if not s:
            return None
        if isinstance(s, int):
            return s
        cleaned = "".join(c for c in str(s) if c.isdigit())
        return int(cleaned) if cleaned else None
    
    def _clean_year(self, s) -> Optional[int]:
        if not s:
            return None
        if isinstance(s, int):
            return s
        match = re.search(r"(19|20)\d{2}", str(s))
        return int(match.group()) if match else None
    
    def _extract_dept(self, ville: str, cp: str = None) -> Optional[str]:
        if cp and len(cp) >= 2:
            return cp[:2]
        if ville:
            match = re.search(r"\((\d{2,3})\)", ville)
            if match:
                return match.group(1)[:2]
        return None
    
    def _matches_criteria(self, data: Dict, config: Dict) -> bool:
        """Vérifie si l'annonce correspond aux critères"""
        prix = data.get("prix")
        if prix:
            if prix < config.get("prix_min", 0) or prix > config.get("prix_max", 999999):
                return False
        
        km = data.get("kilometrage")
        if km:
            if km < config.get("km_min", 0) or km > config.get("km_max", 999999):
                return False
        
        annee = data.get("annee")
        if annee:
            if annee < config.get("annee_min", 1990) or annee > config.get("annee_max", 2025):
                return False
        
        # Vérifier les exclusions
        texte = f"{data.get('titre', '')} {data.get('motorisation', '')}".lower()
        for exclu in config.get("motorisation_exclude", []):
            if exclu.lower() in texte:
                return False
        
        return True
    
    def _is_in_zone(self, dept: str) -> bool:
        return not dept or dept in TOUS_DEPARTEMENTS
    
    async def scrape_vehicule(self, vehicule_id: str, config: Dict) -> List[Annonce]:
        """Scrape les annonces pour un véhicule"""
        annonces = []
        page = await self.get_page()
        
        try:
            for page_num in range(1, 4):  # 3 pages max
                url = self.build_search_url(config, page_num)
                logger.debug(f"Scraping {url}")
                
                listings = await self.scrape_page(page, url)
                
                if not listings:
                    break
                
                for data in listings:
                    if self.db.exists(data["url"]):
                        continue
                    
                    dept = self._extract_dept(data.get("ville"), data.get("code_postal"))
                    if not self._is_in_zone(dept):
                        continue
                    
                    if not self._matches_criteria(data, config):
                        continue
                    
                    annonce = Annonce(
                        url=data["url"],
                        source=self.name,
                        marque=data.get("marque") or config.get("marque"),
                        modele=data.get("modele"),
                        carburant=data.get("carburant"),
                        annee=data.get("annee"),
                        kilometrage=data.get("kilometrage"),
                        prix=data.get("prix"),
                        ville=data.get("ville"),
                        departement=dept,
                        titre=data.get("titre"),
                        type_vendeur=data.get("type_vendeur", "particulier"),
                    )
                    annonce.vehicule_cible_id = vehicule_id
                    annonces.append(annonce)
                
                await asyncio.sleep(3)  # Pause entre pages
                
        finally:
            await page.context.close()
        
        return annonces
    
    async def scrape_all(self) -> List[Annonce]:
        """Scrape toutes les annonces"""
        log_scraping_start(self.name)
        all_annonces = []
        new_count = 0
        
        await self.init_browser()
        
        try:
            for vehicule_id, config in VEHICULES_CIBLES.items():
                try:
                    logger.debug(f"Scraping {vehicule_id}...")
                    annonces = await self.scrape_vehicule(vehicule_id, config)
                    
                    for annonce in annonces:
                        is_new = self.db.save_annonce(annonce)
                        if is_new:
                            new_count += 1
                        all_annonces.append(annonce)
                    
                    await asyncio.sleep(5)  # Pause entre véhicules
                    
                except Exception as e:
                    log_error(f"Erreur scraping {vehicule_id}", e)
                    continue
                    
        finally:
            await self.close_browser()
        
        log_scraping_end(self.name, len(all_annonces), new_count)
        self.annonces_trouvees = all_annonces
        return all_annonces
    
    def run(self) -> List[Annonce]:
        """Point d'entrée synchrone"""
        return asyncio.run(self.scrape_all())
