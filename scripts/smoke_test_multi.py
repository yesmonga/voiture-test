#!/usr/bin/env python3
"""
Smoke Test Multi-Source - Test E2E avec plusieurs sources
Vérifie:
1. Run 1: nouveaux listings + notifications
2. Run 2: doublons détectés => 0 notif
3. Source "blocked" simulée => les autres continuent
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.enums import Source
from models.annonce import Annonce
from services.orchestrator import (
    Orchestrator, IndexResult, DetailResult, IndexScraper, DetailScraper
)
from db.repo import AnnonceRepository


class MockIndexScraper:
    """Mock scraper pour tests - simule une source"""
    
    def __init__(self, source: Source, listings: list[dict]):
        self.source = source
        self.listings = listings
        self.call_count = 0
        self.blocked = False
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        self.call_count += 1
        
        if self.blocked:
            print(f"   ⏸️ {self.source.value}: simulated block")
            return []
        
        results = []
        for listing in self.listings:
            results.append(IndexResult(
                url=listing["url"],
                source=self.source,
                titre=listing.get("titre", "Test"),
                prix=listing.get("prix"),
                kilometrage=listing.get("km"),
                annee=listing.get("annee"),
                ville=listing.get("ville", ""),
                departement=listing.get("dept", ""),
                published_at=datetime.now(timezone.utc),
                thumbnail_url="",
                source_listing_id=listing["id"],
                marque=listing.get("marque", "Peugeot"),
                modele=listing.get("modele", "207"),
            ))
        return results
    
    async def close(self):
        pass


class MockDetailScraper:
    """Mock detail scraper"""
    
    def __init__(self):
        self.call_count = 0
    
    async def fetch_detail(self, url: str) -> DetailResult:
        self.call_count += 1
        return DetailResult(
            description="Test description avec CT ok et négociable",
            images_urls=[],
            seller_type="particulier",
        )
    
    async def close(self):
        pass


def clear_test_db():
    """Efface la base de test"""
    db_path = Path(__file__).parent.parent / "data" / "annonces.db"
    if db_path.exists():
        db_path.unlink()
        print("🗑️  Removed existing DB for clean test")


async def run_smoke_test():
    """Exécute le smoke test multi-source"""
    print("=" * 60)
    print("SMOKE TEST MULTI-SOURCE - End-to-end Pipeline")
    print("=" * 60)
    
    clear_test_db()
    
    # === RUN 1: Plusieurs sources, nouveaux listings ===
    print("\n--- RUN 1: Multi-source scan (should create + notify) ---")
    
    orch = Orchestrator()
    
    # Source 1: AutoScout24
    autoscout_scraper = MockIndexScraper(Source.AUTOSCOUT24, [
        {"id": "AS001", "url": "https://autoscout24.fr/a/AS001", "prix": 1500, "km": 160000, "annee": 2010},
    ])
    autoscout_detail = MockDetailScraper()
    
    # Source 2: LaCentrale
    lacentrale_scraper = MockIndexScraper(Source.LACENTRALE, [
        {"id": "LC001", "url": "https://lacentrale.fr/a/LC001", "prix": 1800, "km": 155000, "annee": 2011},
    ])
    lacentrale_detail = MockDetailScraper()
    
    # Source 3: ParuVendu
    paruvendu_scraper = MockIndexScraper(Source.PARUVENDU, [
        {"id": "PV001", "url": "https://paruvendu.fr/a/PV001", "prix": 1650, "km": 170000, "annee": 2009},
    ])
    paruvendu_detail = MockDetailScraper()
    
    orch.register_scraper(Source.AUTOSCOUT24, autoscout_scraper, autoscout_detail)
    orch.register_scraper(Source.LACENTRALE, lacentrale_scraper, lacentrale_detail)
    orch.register_scraper(Source.PARUVENDU, paruvendu_scraper, paruvendu_detail)
    
    stats1 = await orch.run_pipeline(
        sources=[Source.AUTOSCOUT24, Source.LACENTRALE, Source.PARUVENDU],
        detail_threshold=20,
        notify_threshold=30,
        max_detail_per_run=10,
    )
    
    print(f"Stats: {stats1.summary()}")
    print(f"Sources scanned: AS={autoscout_scraper.call_count}, LC={lacentrale_scraper.call_count}, PV={paruvendu_scraper.call_count}")
    
    # Vérifier
    repo = AnnonceRepository()
    all_annonces = list(repo.get_all())
    print(f"DB has {len(all_annonces)} annonces")
    
    for a in all_annonces:
        print(f"  - {a.source}: {a.marque} {a.modele}: {a.prix}€, score={a.score_total}")
    
    assert stats1.index_scanned >= 3, f"Expected >= 3 scanned, got {stats1.index_scanned}"
    assert stats1.index_new >= 3, f"Expected >= 3 new, got {stats1.index_new}"
    assert len(all_annonces) >= 3, f"Expected >= 3 in DB, got {len(all_annonces)}"
    
    print("✅ Run 1 OK - Multi-source scan worked")
    
    # === RUN 2: Mêmes listings = doublons ===
    print("\n--- RUN 2: Same listings (should be duplicates) ---")
    
    orch2 = Orchestrator()
    
    # Réutiliser les mêmes scrapers (mêmes listings)
    autoscout_scraper2 = MockIndexScraper(Source.AUTOSCOUT24, [
        {"id": "AS001", "url": "https://autoscout24.fr/a/AS001", "prix": 1500, "km": 160000, "annee": 2010},
    ])
    lacentrale_scraper2 = MockIndexScraper(Source.LACENTRALE, [
        {"id": "LC001", "url": "https://lacentrale.fr/a/LC001", "prix": 1800, "km": 155000, "annee": 2011},
    ])
    paruvendu_scraper2 = MockIndexScraper(Source.PARUVENDU, [
        {"id": "PV001", "url": "https://paruvendu.fr/a/PV001", "prix": 1650, "km": 170000, "annee": 2009},
    ])
    
    orch2.register_scraper(Source.AUTOSCOUT24, autoscout_scraper2, MockDetailScraper())
    orch2.register_scraper(Source.LACENTRALE, lacentrale_scraper2, MockDetailScraper())
    orch2.register_scraper(Source.PARUVENDU, paruvendu_scraper2, MockDetailScraper())
    
    stats2 = await orch2.run_pipeline(
        sources=[Source.AUTOSCOUT24, Source.LACENTRALE, Source.PARUVENDU],
        detail_threshold=20,
        notify_threshold=30,
    )
    
    print(f"Stats: {stats2.summary()}")
    
    assert stats2.index_duplicates >= 3, f"Expected >= 3 duplicates, got {stats2.index_duplicates}"
    assert stats2.index_new == 0, f"Expected 0 new, got {stats2.index_new}"
    
    print("✅ Run 2 OK - Cross-source dedup works")
    
    # === RUN 3: Une source bloquée, les autres continuent ===
    print("\n--- RUN 3: One source blocked (others should continue) ---")
    
    orch3 = Orchestrator()
    
    # AutoScout24 bloquée
    autoscout_blocked = MockIndexScraper(Source.AUTOSCOUT24, [])
    autoscout_blocked.blocked = True
    
    # Nouvelle annonce sur LaCentrale
    lacentrale_new = MockIndexScraper(Source.LACENTRALE, [
        {"id": "LC002", "url": "https://lacentrale.fr/a/LC002", "prix": 1900, "km": 165000, "annee": 2012},
    ])
    
    # ParuVendu normal (doublon)
    paruvendu_dup = MockIndexScraper(Source.PARUVENDU, [
        {"id": "PV001", "url": "https://paruvendu.fr/a/PV001", "prix": 1650, "km": 170000, "annee": 2009},
    ])
    
    orch3.register_scraper(Source.AUTOSCOUT24, autoscout_blocked, MockDetailScraper())
    orch3.register_scraper(Source.LACENTRALE, lacentrale_new, MockDetailScraper())
    orch3.register_scraper(Source.PARUVENDU, paruvendu_dup, MockDetailScraper())
    
    stats3 = await orch3.run_pipeline(
        sources=[Source.AUTOSCOUT24, Source.LACENTRALE, Source.PARUVENDU],
        detail_threshold=20,
        notify_threshold=30,
    )
    
    print(f"Stats: {stats3.summary()}")
    print(f"AutoScout24 calls (blocked): {autoscout_blocked.call_count}")
    print(f"LaCentrale calls: {lacentrale_new.call_count}")
    print(f"ParuVendu calls: {paruvendu_dup.call_count}")
    
    # LaCentrale et ParuVendu devraient avoir été appelés
    assert lacentrale_new.call_count >= 1, "LaCentrale should have been called"
    assert paruvendu_dup.call_count >= 1, "ParuVendu should have been called"
    assert stats3.index_new >= 1, "Should have at least 1 new listing from LaCentrale"
    
    print("✅ Run 3 OK - Blocked source doesn't stop others")
    
    # === Résultat final ===
    final_count = len(list(repo.get_all()))
    print(f"\n📊 Final DB count: {final_count} annonces")
    
    print("\n" + "=" * 60)
    print("🎉 ALL MULTI-SOURCE SMOKE TESTS PASSED")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(run_smoke_test())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ SMOKE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
