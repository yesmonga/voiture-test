#!/usr/bin/env python3
"""
SCAN COMPLET - LeBoncoin + AutoScout24
Trouve les meilleures affaires avec véhicules en l'état / petits problèmes
"""

import asyncio
import httpx
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from playwright.async_api import async_playwright

from models.annonce import Annonce
from models.database import get_db
from services.scorer import ScoringService
from services.notifier import NotificationService
from utils.anti_bot import anti_bot
from config import VEHICULES_CIBLES, MOTS_CLES_OPPORTUNITE

# Véhicules cibles à scanner
VEHICULES = [
    # Priorité 1 - Peugeot 207 HDi
    {"marque": "peugeot", "modele": "207", "carburant": "D", "prix_max": 3500, "km_max": 220000},
    # Priorité 2 - Renault Clio III
    {"marque": "renault", "modele": "clio", "carburant": "D", "prix_max": 3500, "km_max": 200000},
    {"marque": "renault", "modele": "clio", "carburant": "B", "prix_max": 3500, "km_max": 180000},
    # Priorité 3 - Dacia Sandero
    {"marque": "dacia", "modele": "sandero", "carburant": "", "prix_max": 4000, "km_max": 180000},
    # Priorité 3 - Renault Twingo II
    {"marque": "renault", "modele": "twingo", "carburant": "", "prix_max": 3500, "km_max": 160000},
    # Priorité 4 - Ford Fiesta
    {"marque": "ford", "modele": "fiesta", "carburant": "", "prix_max": 4500, "km_max": 180000},
    # Priorité 4 - Toyota Yaris
    {"marque": "toyota", "modele": "yaris", "carburant": "B", "prix_max": 4500, "km_max": 180000},
]


class FullScanner:
    def __init__(self):
        self.db = get_db()
        self.scorer = ScoringService()
        self.notifier = NotificationService()
        self.all_annonces: List[Annonce] = []
    
    # ==================== AUTOSCOUT24 ====================
    async def scan_autoscout(self):
        """Scan complet AutoScout24"""
        print("\n" + "=" * 60)
        print("🔵 AUTOSCOUT24 - SCAN COMPLET")
        print("=" * 60)
        
        for v in VEHICULES:
            await asyncio.sleep(2)
            annonces = await self._scrape_autoscout_vehicle(v)
            self.all_annonces.extend(annonces)
    
    async def _scrape_autoscout_vehicle(self, v: Dict) -> List[Annonce]:
        proxy = anti_bot.get_proxy()
        headers = anti_bot.get_headers()
        
        fuel = f"&fuel={v['carburant']}" if v['carburant'] else ""
        url = f"https://www.autoscout24.fr/lst/{v['marque']}/{v['modele']}?cy=F&atype=C&sort=age&desc=1&priceto={v['prix_max']}&kmto={v['km_max']}{fuel}"
        
        print(f"  🔍 {v['marque'].title()} {v['modele'].title()}...", end=" ", flush=True)
        
        annonces = []
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=25, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
                
                if r.status_code != 200:
                    print(f"❌ {r.status_code}")
                    return []
                
                soup = BeautifulSoup(r.text, "lxml")
                articles = soup.find_all("article")
                
                for art in articles:
                    annonce = self._parse_autoscout_article(art, v)
                    if annonce and not self.db.exists(annonce.url):
                        self.scorer.calculer_score(annonce)
                        self.db.save_annonce(annonce)
                        annonces.append(annonce)
                
                print(f"✅ {len(annonces)} nouvelles")
                
        except Exception as e:
            print(f"❌ {str(e)[:25]}")
        
        return annonces
    
    def _parse_autoscout_article(self, art, v: Dict) -> Optional[Annonce]:
        try:
            h2 = art.find("h2")
            if not h2:
                return None
            titre = h2.get_text(strip=True)
            
            link = art.find("a", href=True)
            href = link.get("href", "") if link else ""
            if not href:
                return None
            url = href if href.startswith("http") else f"https://www.autoscout24.fr{href}"
            
            text = art.get_text()
            
            # Prix
            prix = None
            for t in art.stripped_strings:
                if "€" in t:
                    cleaned = re.sub(r"[^\d]", "", t)
                    if cleaned and 500 < int(cleaned) < 50000:
                        prix = int(cleaned)
                        break
            
            # Km
            km = None
            km_m = re.search(r"(\d{1,3}(?:[\s\.\u202f]\d{3})*)\s*km", text, re.I)
            if km_m:
                km_str = re.sub(r"[^\d]", "", km_m.group(1))
                if km_str and 1000 < int(km_str) < 500000:
                    km = int(km_str)
            
            # Année
            annee = None
            y_m = re.search(r"[-/](20[0-2]\d)\b", text)
            if y_m:
                annee = int(y_m.group(1))
            
            # Carburant
            carb = "Diesel" if any(x in text.lower() for x in ["diesel", "hdi", "dci", "tdi"]) else "Essence"
            
            # Détection mots-clés opportunité
            mots_cles = []
            text_lower = text.lower()
            for mot in MOTS_CLES_OPPORTUNITE:
                if mot.lower() in text_lower:
                    mots_cles.append(mot)
            
            return Annonce(
                url=url,
                source="autoscout24",
                marque=v["marque"].title(),
                modele=v["modele"].title(),
                titre=titre,
                prix=prix,
                kilometrage=km,
                annee=annee,
                carburant=carb,
                type_vendeur="particulier",
                date_publication=datetime.now(),
                mots_cles_detectes=mots_cles,
            )
        except:
            return None
    
    # ==================== LEBONCOIN ====================
    async def scan_leboncoin(self):
        """Scan LeBoncoin avec Playwright"""
        print("\n" + "=" * 60)
        print("🟠 LEBONCOIN - SCAN COMPLET (Playwright)")
        print("=" * 60)
        
        playwright = await async_playwright().start()
        
        # Config proxy
        proxy_url = anti_bot.get_proxy()
        proxy_config = None
        if proxy_url:
            match = re.match(r"http://([^:]+):([^@]+)@([^:]+):(\d+)", proxy_url)
            if match:
                proxy_config = {
                    "server": f"http://{match.group(3)}:{match.group(4)}",
                    "username": match.group(1),
                    "password": match.group(2)
                }
        
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        
        try:
            for v in VEHICULES:
                await asyncio.sleep(3)
                annonces = await self._scrape_leboncoin_vehicle(browser, proxy_config, v)
                self.all_annonces.extend(annonces)
        finally:
            await browser.close()
            await playwright.stop()
    
    async def _scrape_leboncoin_vehicle(self, browser, proxy_config, v: Dict) -> List[Annonce]:
        print(f"  🔍 {v['marque'].title()} {v['modele'].title()}...", end=" ", flush=True)
        
        # Construire l'URL
        fuel_map = {"D": "2", "B": "1", "": ""}
        fuel = f"&fuel={fuel_map.get(v['carburant'], '')}" if v['carburant'] else ""
        
        url = f"https://www.leboncoin.fr/recherche?category=2&brand={v['marque']}&model={v['modele']}&price=1500-{v['prix_max']}&mileage=50000-{v['km_max']}&locations=r_12&owner_type=private&sort=time&order=desc{fuel}"
        
        annonces = []
        try:
            context = await browser.new_context(
                user_agent=anti_bot.get_random_user_agent(),
                viewport={"width": 1920, "height": 1080},
                locale="fr-FR",
                proxy=proxy_config
            )
            page = await context.new_page()
            
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            
            # Accepter cookies
            try:
                btn = page.locator("button:has-text('Accepter')")
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(1)
            except:
                pass
            
            # Scroll pour charger
            await page.evaluate("window.scrollTo(0, 1000)")
            await asyncio.sleep(2)
            
            content = await page.content()
            soup = BeautifulSoup(content, "lxml")
            
            # Parser les annonces
            cards = soup.select("a[data-qa-id='aditem_container']")
            if not cards:
                cards = soup.select("a[href*='/ad/voitures/']")
            
            for card in cards[:20]:
                annonce = self._parse_leboncoin_card(card, v)
                if annonce and not self.db.exists(annonce.url):
                    self.scorer.calculer_score(annonce)
                    self.db.save_annonce(annonce)
                    annonces.append(annonce)
            
            await context.close()
            print(f"✅ {len(annonces)} nouvelles")
            
        except Exception as e:
            print(f"❌ {str(e)[:30]}")
        
        return annonces
    
    def _parse_leboncoin_card(self, card, v: Dict) -> Optional[Annonce]:
        try:
            href = card.get("href", "")
            if not href or "/ad/" not in href:
                return None
            url = href if href.startswith("http") else f"https://www.leboncoin.fr{href}"
            
            # Titre
            title_elem = card.select_one("[data-qa-id='aditem_title']") or card.find("p")
            titre = title_elem.get_text(strip=True) if title_elem else None
            
            # Prix
            prix = None
            price_elem = card.select_one("[data-qa-id='aditem_price']")
            if price_elem:
                cleaned = re.sub(r"[^\d]", "", price_elem.get_text())
                if cleaned:
                    prix = int(cleaned)
            
            # Localisation
            loc_elem = card.select_one("[data-qa-id='aditem_location']")
            ville = loc_elem.get_text(strip=True) if loc_elem else None
            
            # Extraire département
            dept = None
            if ville:
                m = re.search(r"\((\d{2})\)", ville)
                if m:
                    dept = m.group(1)
            
            text = card.get_text().lower()
            
            # Mots-clés
            mots_cles = []
            for mot in MOTS_CLES_OPPORTUNITE:
                if mot.lower() in text:
                    mots_cles.append(mot)
            
            return Annonce(
                url=url,
                source="leboncoin",
                marque=v["marque"].title(),
                modele=v["modele"].title(),
                titre=titre,
                prix=prix,
                ville=ville,
                departement=dept,
                type_vendeur="particulier",
                date_publication=datetime.now(),
                mots_cles_detectes=mots_cles,
            )
        except:
            return None
    
    # ==================== RESULTATS ====================
    async def show_and_notify(self):
        """Affiche et notifie les meilleures annonces"""
        # Trier par score
        self.all_annonces.sort(key=lambda a: a.score_rentabilite, reverse=True)
        
        print("\n" + "=" * 60)
        print(f"🏆 TOP {min(20, len(self.all_annonces))} MEILLEURES AFFAIRES")
        print("=" * 60)
        
        for i, a in enumerate(self.all_annonces[:20], 1):
            km_str = f"{a.kilometrage:,}km" if a.kilometrage else "?km"
            mots = f" 🔑{','.join(a.mots_cles_detectes[:2])}" if a.mots_cles_detectes else ""
            print(f"{i:2}. [{a.score_rentabilite:3}/100] {a.source[:4]:4} | {a.marque} {a.modele} | {a.prix or '?':>5}€ | {km_str:>10}{mots}")
            print(f"    └─ {a.url}")
        
        # Envoyer sur Discord
        print("\n" + "=" * 60)
        print("📤 ENVOI DISCORD - MEILLEURES OFFRES")
        print("=" * 60)
        
        sent = 0
        for a in self.all_annonces[:15]:
            if a.prix:
                print(f"🔔 {a.marque} {a.modele} - {a.prix}€ - Score {a.score_rentabilite}...", end=" ")
                success = await self.notifier.send_discord(a)
                print("✅" if success else "❌")
                if success:
                    self.db.mark_notified(a.id)
                    sent += 1
                await asyncio.sleep(1.2)
        
        print(f"\n✅ {sent} notifications envoyées!")
        
        # Stats
        print("\n" + "=" * 60)
        print("📊 STATISTIQUES")
        print("=" * 60)
        print(f"Total annonces trouvées: {len(self.all_annonces)}")
        print(f"Avec mots-clés opportunité: {sum(1 for a in self.all_annonces if a.mots_cles_detectes)}")
        print(f"Score >= 50: {sum(1 for a in self.all_annonces if a.score_rentabilite >= 50)}")
        print(f"Score >= 30: {sum(1 for a in self.all_annonces if a.score_rentabilite >= 30)}")


async def main():
    print("=" * 60)
    print("🚗 SCAN COMPLET - LEBONCOIN + AUTOSCOUT24")
    print("   Recherche des véhicules en l'état / petits problèmes")
    print("=" * 60)
    
    scanner = FullScanner()
    
    # Scan AutoScout24
    await scanner.scan_autoscout()
    
    # Scan LeBoncoin
    await scanner.scan_leboncoin()
    
    # Résultats
    await scanner.show_and_notify()
    
    print("\n✅ SCAN TERMINÉ - Vérifie Discord!")


if __name__ == "__main__":
    asyncio.run(main())
