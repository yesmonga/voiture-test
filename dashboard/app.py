#!/usr/bin/env python3
"""
Dashboard Web - FastAPI + HTMX
Visualisation des annonces et statistiques
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db.repo import get_repo
from models.enums import Source, AlertLevel

# App
app = FastAPI(title="Voitures Bot Dashboard", version="1.0.0")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# === Helpers ===

def format_price(price: Optional[int]) -> str:
    if price is None:
        return "N/C"
    return f"{price:,} €".replace(",", " ")


def format_km(km: Optional[int]) -> str:
    if km is None:
        return "N/C"
    return f"{km:,} km".replace(",", " ")


def time_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return "N/C"
    
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    diff = now - dt
    
    if diff < timedelta(minutes=1):
        return "à l'instant"
    elif diff < timedelta(hours=1):
        mins = int(diff.total_seconds() / 60)
        return f"il y a {mins} min"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"il y a {hours}h"
    elif diff < timedelta(days=7):
        days = diff.days
        return f"il y a {days}j"
    else:
        return dt.strftime("%d/%m/%Y")


# Register filters
templates.env.filters["format_price"] = format_price
templates.env.filters["format_km"] = format_km
templates.env.filters["time_ago"] = time_ago


# === Routes ===

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Page d'accueil avec stats"""
    repo = get_repo()
    stats = repo.get_stats()
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
    })


@app.get("/annonces", response_class=HTMLResponse)
async def annonces_list(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    source: Optional[str] = None,
    min_score: int = Query(0, ge=0),
    alert_level: Optional[str] = None,
):
    """Liste des annonces avec filtres"""
    repo = get_repo()
    
    offset = (page - 1) * limit
    
    # Filtres
    filters = {}
    if source:
        filters["source"] = source
    if min_score > 0:
        filters["min_score"] = min_score
    if alert_level:
        filters["alert_level"] = alert_level
    
    annonces = repo.get_all(
        limit=limit,
        offset=offset,
        order_by="created_at DESC",
        **filters
    )
    
    total = repo.count(**filters)
    total_pages = (total + limit - 1) // limit
    
    # Check if HTMX request
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/annonces_table.html", {
            "request": request,
            "annonces": annonces,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        })
    
    return templates.TemplateResponse("annonces.html", {
        "request": request,
        "annonces": annonces,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "sources": [s.value for s in Source],
        "alert_levels": [a.value for a in AlertLevel],
        "filters": {
            "source": source,
            "min_score": min_score,
            "alert_level": alert_level,
        },
    })


@app.get("/annonces/{annonce_id}", response_class=HTMLResponse)
async def annonce_detail(request: Request, annonce_id: str):
    """Détail d'une annonce"""
    repo = get_repo()
    annonce = repo.get_by_id(annonce_id)
    
    if not annonce:
        return HTMLResponse("<h1>Annonce non trouvée</h1>", status_code=404)
    
    return templates.TemplateResponse("annonce_detail.html", {
        "request": request,
        "annonce": annonce,
    })


@app.get("/api/stats")
async def api_stats():
    """API: Statistiques JSON"""
    repo = get_repo()
    return repo.get_stats()


@app.get("/api/annonces")
async def api_annonces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    min_score: int = Query(0, ge=0),
):
    """API: Liste annonces JSON"""
    repo = get_repo()
    annonces = repo.get_all(limit=limit, offset=offset, min_score=min_score)
    return [a.to_dict() for a in annonces]


# === Main ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
