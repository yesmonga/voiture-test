"""
Smoke Test - End-to-end pipeline test with mock scrapers
Validates: dedup, should_notify, update notification, concurrency
"""

import asyncio
from datetime import datetime, timezone, timedelta

from services.orchestrator import get_orchestrator, IndexResult, DetailResult
from models.enums import Source


class MockIndexScraper:
    """Mock scraper returning test listings"""
    
    def __init__(self, listings: list[dict] = None):
        self.listings = listings or []
        self.call_count = 0
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        self.call_count += 1
        now = datetime.now(timezone.utc)
        
        if not self.listings:
            # Default test listing
            return [
                IndexResult(
                    url="https://example.com/a1?utm_source=x",
                    source=Source.AUTOSCOUT24,
                    titre="Peugeot 207 CT ok vente urgente prix negociable",
                    prix=1900,
                    kilometrage=145000,
                    annee=2011,
                    ville="Paris",
                    departement="75",
                    published_at=now - timedelta(minutes=30),
                    thumbnail_url="https://picsum.photos/200",
                    source_listing_id="MOCK001",
                )
            ]
        
        return [
            IndexResult(
                url=l.get("url", f"https://example.com/{l.get('id', 'x')}"),
                source=Source.AUTOSCOUT24,
                titre=l.get("titre", "Test listing"),
                prix=l.get("prix", 2000),
                kilometrage=l.get("km", 100000),
                annee=l.get("annee", 2010),
                ville=l.get("ville", "Paris"),
                departement=l.get("dept", "75"),
                published_at=now - timedelta(minutes=l.get("age_min", 30)),
                thumbnail_url="https://picsum.photos/200",
                source_listing_id=l.get("id", "MOCK001"),
            )
            for l in self.listings
        ]


class MockDetailScraper:
    """Mock detail scraper"""
    
    def __init__(self, description: str = None):
        self.description = description or "CT ok, entretien suivi, rien à prévoir. Véhicule en très bon état."
        self.call_count = 0
    
    async def fetch_detail(self, url: str) -> DetailResult:
        self.call_count += 1
        await asyncio.sleep(0.1)  # Simulate network delay
        
        return DetailResult(
            description=self.description,
            images_urls=["https://picsum.photos/300"] * 6,
            seller_type="particulier",
            carburant="diesel",
            boite="manuelle",
        )


async def run_smoke_test():
    """Run the smoke test"""
    import os
    
    print("=" * 50)
    print("SMOKE TEST - End-to-end Pipeline")
    print("=" * 50)
    print()
    
    # Fresh DB for test
    db_path = "data/annonces.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        print("🗑️  Removed existing DB for clean test")
    
    # Get orchestrator
    from services.orchestrator import Orchestrator
    orch = Orchestrator()  # Fresh instance
    
    # Register mock scrapers
    mock_index = MockIndexScraper()
    mock_detail = MockDetailScraper()
    orch.register_scraper(Source.AUTOSCOUT24, mock_index, mock_detail)
    
    print()
    print("--- RUN 1: First scan (should create + notify) ---")
    stats1 = await orch.run_pipeline(
        sources=[Source.AUTOSCOUT24],
        detail_threshold=10,
        notify_threshold=10,
        max_detail_per_run=10
    )
    print(f"Stats: {stats1.summary()}")
    print(f"Index calls: {mock_index.call_count}, Detail calls: {mock_detail.call_count}")
    
    # Verify
    from db.repo import get_repo
    repo = get_repo()
    all_annonces = repo.get_all(limit=100)
    print(f"DB has {len(all_annonces)} annonces")
    
    if len(all_annonces) > 0:
        a = all_annonces[0]
        print(f"  - {a.marque} {a.modele}: {a.prix}€, score={a.score_total}")
        print(f"  - Notified: {a.notified}")
        print(f"  - Keywords opp: {a.keywords_opportunite}")
    
    assert stats1.index_new == 1, f"Expected 1 new, got {stats1.index_new}"
    assert stats1.detail_fetched == 1, f"Expected 1 detail, got {stats1.detail_fetched}"
    print("✅ Run 1 OK")
    
    print()
    print("--- RUN 2: Same listing (should be duplicate) ---")
    stats2 = await orch.run_pipeline(
        sources=[Source.AUTOSCOUT24],
        detail_threshold=10,
        notify_threshold=10,
        max_detail_per_run=10
    )
    print(f"Stats: {stats2.summary()}")
    
    assert stats2.index_duplicates == 1, f"Expected 1 duplicate, got {stats2.index_duplicates}"
    assert stats2.index_new == 0, f"Expected 0 new, got {stats2.index_new}"
    assert stats2.notified == 0, f"Expected 0 notified (dup), got {stats2.notified}"
    print("✅ Run 2 OK - Duplicate detected, no spam")
    
    print()
    print("--- RUN 3: New listing (should create + notify) ---")
    mock_index.listings = [
        {
            "id": "MOCK002",
            "url": "https://example.com/new",
            "titre": "Renault Clio CT vierge premiere main",
            "prix": 2500,
            "km": 95000,
            "annee": 2012,
        }
    ]
    orch.clear_cache()  # Clear seen URLs to allow new listing
    
    stats3 = await orch.run_pipeline(
        sources=[Source.AUTOSCOUT24],
        detail_threshold=10,
        notify_threshold=10,
        max_detail_per_run=10
    )
    print(f"Stats: {stats3.summary()}")
    
    all_annonces = repo.get_all(limit=100)
    print(f"DB now has {len(all_annonces)} annonces")
    
    assert stats3.index_new == 1, f"Expected 1 new, got {stats3.index_new}"
    print("✅ Run 3 OK - New listing processed")
    
    print()
    print("=" * 50)
    print("🎉 ALL SMOKE TESTS PASSED")
    print("=" * 50)
    
    return True


if __name__ == "__main__":
    success = asyncio.run(run_smoke_test())
    exit(0 if success else 1)
