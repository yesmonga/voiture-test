#!/usr/bin/env python3
"""
CLI - Interface en ligne de commande avec Typer
Commandes: scan, stats, export, test-notifs
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from config.settings import get_settings, DATA_DIR
from db.repo import get_repo, AnnonceRepository
from models.enums import Source, AlertLevel, AnnonceStatus
from models.annonce_v2 import Annonce
from services.scoring import get_scoring_service

# Typer app
app = typer.Typer(
    name="voitures-bot",
    help="Bot de détection d'annonces de voitures d'occasion",
    add_completion=False
)

console = Console()


# === Commandes ===

@app.command()
def scan(
    source: Optional[str] = typer.Option(
        None, "--source", "-s",
        help="Source spécifique (autoscout24, leboncoin)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Nombre max d'annonces à traiter"
    ),
    notify: bool = typer.Option(
        True, "--notify/--no-notify",
        help="Envoyer les notifications Discord"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Mode simulation (pas de sauvegarde)"
    )
):
    """
    Lance un scan des annonces.
    
    Exemples:
        python cli.py scan
        python cli.py scan --source autoscout24
        python cli.py scan --no-notify --dry-run
    """
    console.print(Panel.fit(
        "[bold blue]🚗 Scan des annonces[/bold blue]",
        border_style="blue"
    ))
    
    if source:
        console.print(f"  Source: [cyan]{source}[/cyan]")
    console.print(f"  Limite: [cyan]{limit}[/cyan]")
    console.print(f"  Notifications: [cyan]{'Oui' if notify else 'Non'}[/cyan]")
    console.print(f"  Dry run: [cyan]{'Oui' if dry_run else 'Non'}[/cyan]")
    console.print()
    
    # Import ici pour éviter circular imports
    try:
        asyncio.run(_run_scan(source, limit, notify, dry_run))
    except KeyboardInterrupt:
        console.print("\n[yellow]Scan interrompu[/yellow]")
    except Exception as e:
        console.print(f"[red]Erreur: {e}[/red]")
        raise typer.Exit(1)


async def _run_scan(
    source: Optional[str],
    limit: int,
    notify: bool,
    dry_run: bool
):
    """Exécute le scan de manière asynchrone"""
    from utils.http import get_http_manager
    from services.scoring import get_scoring_service
    
    repo = get_repo()
    scorer = get_scoring_service()
    http = get_http_manager()
    
    # Charger les proxies
    settings = get_settings()
    if settings.proxy.urls:
        http.set_proxies(settings.proxy.urls)
    
    console.print("[dim]Démarrage du scan...[/dim]")
    
    # TODO: Implémenter les scrapers index/detail
    # Pour l'instant, message informatif
    console.print("""
[yellow]⚠️ Scrapers en cours de refactoring[/yellow]

Les nouveaux scrapers (index + detail) seront implémentés prochainement.
Pour tester le scoring et les notifications, utilisez:

  python cli.py test-notifs
  python cli.py stats
""")


@app.command()
def stats():
    """
    Affiche les statistiques des annonces.
    """
    repo = get_repo()
    
    console.print(Panel.fit(
        "[bold green]📊 Statistiques[/bold green]",
        border_style="green"
    ))
    
    # Stats globales
    global_stats = repo.get_stats()
    
    if global_stats:
        table = Table(title="Vue d'ensemble")
        table.add_column("Métrique", style="cyan")
        table.add_column("Valeur", style="green", justify="right")
        
        table.add_row("Total annonces", str(global_stats.get("total_annonces", 0)))
        table.add_row("Nouveaux", str(global_stats.get("nouveaux", 0)))
        table.add_row("Urgents (≥80)", str(global_stats.get("urgents", 0)))
        table.add_row("Intéressants (≥60)", str(global_stats.get("interessants", 0)))
        table.add_row("Notifiées", str(global_stats.get("notifiees", 0)))
        
        score_moyen = global_stats.get("score_moyen")
        if score_moyen:
            table.add_row("Score moyen", f"{score_moyen:.1f}")
        
        prix_moyen = global_stats.get("prix_moyen")
        if prix_moyen:
            table.add_row("Prix moyen", f"{int(prix_moyen):,} €".replace(",", " "))
        
        km_moyen = global_stats.get("km_moyen")
        if km_moyen:
            table.add_row("Km moyen", f"{int(km_moyen):,} km".replace(",", " "))
        
        console.print(table)
        console.print()
    
    # Stats par source
    source_stats = repo.get_stats_by_source()
    
    if source_stats:
        table = Table(title="Par source")
        table.add_column("Source", style="cyan")
        table.add_column("Total", justify="right")
        table.add_column("Aujourd'hui", justify="right")
        table.add_column("Score moyen", justify="right")
        table.add_column("Score max", justify="right")
        
        for s in source_stats:
            score_moy = f"{s.get('score_moyen', 0):.1f}" if s.get('score_moyen') else "-"
            table.add_row(
                s.get("source", "?"),
                str(s.get("total", 0)),
                str(s.get("aujourdhui", 0)),
                score_moy,
                str(s.get("score_max", 0))
            )
        
        console.print(table)
    
    # Top 10
    console.print()
    _show_top_annonces(repo, limit=10)


def _show_top_annonces(repo: AnnonceRepository, limit: int = 10):
    """Affiche les meilleures annonces"""
    annonces = repo.get_all(limit=limit, order_by="score_total DESC")
    
    if not annonces:
        console.print("[dim]Aucune annonce en base[/dim]")
        return
    
    table = Table(title=f"Top {len(annonces)} annonces")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Véhicule", style="cyan", width=25)
    table.add_column("Prix", justify="right", width=10)
    table.add_column("Km", justify="right", width=12)
    table.add_column("Dept", width=5)
    table.add_column("Alerte", width=12)
    
    for i, a in enumerate(annonces, 1):
        vehicule = f"{a.marque} {a.modele}"[:25]
        prix = a.format_prix() if a.prix else "N/C"
        km = a.format_km() if a.kilometrage else "N/C"
        
        alert_style = {
            AlertLevel.URGENT: "[bold red]",
            AlertLevel.INTERESSANT: "[orange1]",
            AlertLevel.SURVEILLER: "[yellow]",
            AlertLevel.ARCHIVE: "[dim]"
        }.get(a.alert_level, "")
        
        table.add_row(
            str(i),
            f"[bold]{a.score_total}[/bold]",
            vehicule,
            prix,
            km,
            a.departement or "-",
            f"{alert_style}{a.alert_level.value}[/]"
        )
    
    console.print(table)


@app.command()
def export(
    output: Path = typer.Option(
        DATA_DIR / "export.csv",
        "--output", "-o",
        help="Fichier de sortie"
    ),
    format: str = typer.Option(
        "csv",
        "--format", "-f",
        help="Format (csv, json)"
    ),
    min_score: int = typer.Option(
        0,
        "--min-score",
        help="Score minimum"
    )
):
    """
    Exporte les annonces en CSV ou JSON.
    """
    repo = get_repo()
    
    annonces = repo.get_all(limit=1000, min_score=min_score)
    
    if not annonces:
        console.print("[yellow]Aucune annonce à exporter[/yellow]")
        return
    
    output.parent.mkdir(parents=True, exist_ok=True)
    
    if format.lower() == "json":
        output = output.with_suffix(".json")
        data = [a.to_dict() for a in annonces]
        with open(output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    else:
        output = output.with_suffix(".csv")
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                "score", "marque", "modele", "prix", "km", "annee",
                "departement", "alert_level", "url", "created_at"
            ])
            
            # Data
            for a in annonces:
                writer.writerow([
                    a.score_total,
                    a.marque,
                    a.modele,
                    a.prix,
                    a.kilometrage,
                    a.annee,
                    a.departement,
                    a.alert_level.value,
                    a.url,
                    a.created_at.isoformat() if a.created_at else ""
                ])
    
    console.print(f"[green]✅ {len(annonces)} annonces exportées vers {output}[/green]")


@app.command("test-notifs")
def test_notifs(
    channel: str = typer.Option(
        "discord",
        "--channel", "-c",
        help="Canal à tester (discord, telegram, email)"
    )
):
    """
    Envoie une notification de test.
    """
    console.print(Panel.fit(
        "[bold yellow]🔔 Test notification[/bold yellow]",
        border_style="yellow"
    ))
    
    asyncio.run(_test_notification(channel))


async def _test_notification(channel: str):
    """Envoie une notification de test"""
    from models.annonce_v2 import Annonce, ScoreBreakdown
    from models.enums import Source, AlertLevel, SellerType, Carburant
    from services.notifier.discord import send_discord_notification
    
    # Créer une annonce de test
    test_annonce = Annonce(
        source=Source.AUTOSCOUT24,
        marque="Peugeot",
        modele="207",
        version="1.4 HDi 70ch Active",
        prix=2500,
        kilometrage=156000,
        annee=2010,
        carburant=Carburant.DIESEL,
        ville="Paris",
        departement="75",
        seller_type=SellerType.PARTICULIER,
        titre="Peugeot 207 1.4 HDi 70ch - Très bon état",
        url="https://www.autoscout24.fr/test-annonce",
        score_total=75,
        alert_level=AlertLevel.INTERESSANT,
        keywords_opportunite=["négociable", "ct ok"],
        keywords_risque=[],
        margin_estimate_min=800,
        margin_estimate_max=1500,
    )
    
    # Mettre à jour le breakdown
    test_annonce.score_breakdown = ScoreBreakdown(
        prix_score=35,
        prix_detail="2500€ (fourchette 1500-3000€)",
        km_score=25,
        km_detail="156 000 km (idéal)",
        freshness_score=8,
        freshness_detail="< 24h",
        keywords_score=7,
        keywords_detail="négociable, ct ok",
        bonus_score=0,
        bonus_detail="",
        risk_penalty=0,
        risk_detail="Aucun risque détecté",
        total=75,
        margin_min=800,
        margin_max=1500,
        repair_cost_estimate=0
    )
    
    console.print(f"Envoi sur [cyan]{channel}[/cyan]...")
    
    if channel.lower() == "discord":
        success = await send_discord_notification(test_annonce)
        if success:
            console.print("[green]✅ Notification Discord envoyée![/green]")
        else:
            console.print("[red]❌ Échec de l'envoi Discord[/red]")
    else:
        console.print(f"[yellow]Canal '{channel}' non implémenté[/yellow]")


@app.command()
def show(
    annonce_id: str = typer.Argument(..., help="ID de l'annonce")
):
    """
    Affiche les détails d'une annonce.
    """
    repo = get_repo()
    annonce = repo.get_by_id(annonce_id)
    
    if not annonce:
        console.print(f"[red]Annonce non trouvée: {annonce_id}[/red]")
        raise typer.Exit(1)
    
    # Afficher les détails
    console.print(Panel.fit(
        f"[bold]{annonce.marque} {annonce.modele}[/bold]",
        border_style="cyan"
    ))
    
    console.print(f"  [dim]ID:[/dim] {annonce.id}")
    console.print(f"  [dim]Source:[/dim] {annonce.source.value}")
    console.print(f"  [dim]Score:[/dim] [bold]{annonce.score_total}/100[/bold] ({annonce.alert_level.value})")
    console.print()
    console.print(f"  💰 Prix: {annonce.format_prix()}")
    console.print(f"  🛣️ Km: {annonce.format_km()}")
    console.print(f"  📅 Année: {annonce.annee or 'N/C'}")
    console.print(f"  ⛽ Carburant: {annonce.carburant.value}")
    console.print(f"  📍 Localisation: {annonce.ville or ''} ({annonce.departement or '?'})")
    console.print()
    
    # Score breakdown
    if annonce.score_breakdown:
        console.print("[bold]Score breakdown:[/bold]")
        sb = annonce.score_breakdown
        console.print(f"  • Prix: {sb.prix_score} pts - {sb.prix_detail}")
        console.print(f"  • Km: {sb.km_score} pts - {sb.km_detail}")
        console.print(f"  • Fraîcheur: {sb.freshness_score} pts - {sb.freshness_detail}")
        console.print(f"  • Mots-clés: {sb.keywords_score} pts - {sb.keywords_detail}")
        console.print(f"  • Bonus: {sb.bonus_score} pts - {sb.bonus_detail}")
        console.print(f"  • Risques: {sb.risk_penalty} pts - {sb.risk_detail}")
        console.print()
        console.print(f"  💵 Marge estimée: {sb.margin_min:,} - {sb.margin_max:,} €".replace(",", " "))
    
    console.print()
    console.print(f"  🔗 {annonce.url}")


@app.command()
def version():
    """Affiche la version du bot."""
    console.print("[bold blue]voitures-bot[/bold blue] v2.0.0")
    console.print("  Architecture: Production-grade")
    console.print("  Python: 3.11+")


# === Entry point ===

if __name__ == "__main__":
    app()
