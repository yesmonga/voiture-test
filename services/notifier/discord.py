"""
Discord Notifier V2 - Notifications intelligentes
- Raison en 1 ligne pour décision rapide
- Détection prix baissé / score monté
- Embeds riches avec score breakdown
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from models.annonce_v2 import Annonce
from models.enums import AlertLevel
from config.settings import get_settings


def get_embed_color(alert_level: AlertLevel) -> int:
    """Retourne la couleur de l'embed selon le niveau d'alerte"""
    settings = get_settings()
    colors = {
        AlertLevel.URGENT: settings.discord.embed_color_urgent,
        AlertLevel.INTERESSANT: settings.discord.embed_color_interessant,
        AlertLevel.SURVEILLER: settings.discord.embed_color_surveiller,
        AlertLevel.ARCHIVE: settings.discord.embed_color_archive,
    }
    return colors.get(alert_level, 0x808080)


def get_alert_emoji(alert_level: AlertLevel) -> str:
    """Retourne l'emoji selon le niveau d'alerte"""
    emojis = {
        AlertLevel.URGENT: "🔴",
        AlertLevel.INTERESSANT: "🟠",
        AlertLevel.SURVEILLER: "🟡",
        AlertLevel.ARCHIVE: "⚪",
    }
    return emojis.get(alert_level, "⚪")


async def send_discord_notification(annonce: Annonce) -> bool:
    """
    Envoie une notification Discord avec embed riche.
    
    Args:
        annonce: L'annonce à notifier
        
    Returns:
        True si envoi réussi, False sinon
    """
    settings = get_settings()
    
    # Vérifier la config
    webhook_url = settings.discord.webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    
    if not webhook_url:
        print("⚠️ Discord webhook URL non configuré")
        return False
    
    if not settings.discord.enabled:
        print("⚠️ Discord notifications désactivées")
        return False
    
    # Construire l'embed
    embed = _build_embed(annonce)
    
    # Payload Discord
    payload = {
        "embeds": [embed],
        "username": "Voitures Bot",
    }
    
    # Envoyer
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in (200, 204):
                return True
            else:
                print(f"❌ Discord error: {response.status_code} - {response.text}")
                return False
                
    except httpx.HTTPError as e:
        print(f"❌ Discord HTTP error: {e}")
        return False
    except Exception as e:
        print(f"❌ Discord error: {e}")
        return False


def _build_reason_line(annonce: Annonce) -> str:
    """
    Construit une raison en 1 ligne pour décision rapide.
    Ex: "🔥 -22% marché + CT OK + 1ère main + 75"
    """
    reasons = []
    
    # Prix vs marché
    if annonce.score_breakdown and annonce.score_breakdown.prix_detail:
        detail = annonce.score_breakdown.prix_detail
        if "%" in detail:
            # Extraire le pourcentage
            import re
            match = re.search(r'-?(\d+)%', detail)
            if match:
                reasons.append(f"-{match.group(1)}% marché")
        elif "très bas" in detail.lower() or "bonne affaire" in detail.lower():
            reasons.append("🔥 Prix bas")
    
    # Mots-clés opportunité
    if annonce.keywords_opportunite:
        kw_display = {
            "ct_ok": "CT OK",
            "urgent": "Urgent",
            "urgent_vente": "Vente urgente",
            "negociable": "Négo",
            "premiere_main": "1ère main",
            "entretien_suivi": "Entretien OK",
            "faible_km": "Faible km",
        }
        for kw in annonce.keywords_opportunite[:3]:
            reasons.append(kw_display.get(kw, kw.replace("_", " ").title()))
    
    # Département si prioritaire
    if annonce.departement:
        reasons.append(annonce.departement)
    
    # Vendeur
    if annonce.seller_type and annonce.seller_type.value == "particulier":
        reasons.append("Particulier")
    
    # Risques (warning)
    if annonce.keywords_risque:
        risk_display = {
            "ct_refuse": "⚠️ CT",
            "moteur_hs": "❌ Moteur",
            "prix_a_verifier": "❓ Prix",
        }
        for risk in annonce.keywords_risque[:2]:
            if risk in risk_display:
                reasons.append(risk_display[risk])
    
    if not reasons:
        return ""
    
    return " + ".join(reasons)


def _build_embed(annonce: Annonce, reason: str = "", is_update: bool = False) -> dict:
    """Construit l'embed Discord avec raison en 1 ligne"""
    
    emoji = get_alert_emoji(annonce.alert_level)
    color = get_embed_color(annonce.alert_level)
    
    # Titre
    title = f"{emoji} {annonce.marque} {annonce.modele}"
    if annonce.version:
        title += f" {annonce.version[:25]}"
    
    # Préfixe si mise à jour
    if is_update:
        title = f"🔄 {title}"
    
    # Construire la raison si pas fournie
    if not reason:
        reason = _build_reason_line(annonce)
    
    # Description avec raison en 1 ligne + score
    description_parts = []
    
    if reason:
        description_parts.append(f"**🎯 {reason}**")
    
    description_parts.append(f"Score: **{annonce.score_total}/100** ({annonce.alert_level.value})")
    
    # Breakdown compact
    if annonce.score_breakdown:
        sb = annonce.score_breakdown
        breakdown_items = []
        if sb.prix_score:
            breakdown_items.append(f"Prix:{sb.prix_score}")
        if sb.km_score:
            breakdown_items.append(f"Km:{sb.km_score}")
        if sb.freshness_score:
            breakdown_items.append(f"Fresh:{sb.freshness_score}")
        if sb.keywords_score:
            breakdown_items.append(f"KW:{sb.keywords_score}")
        if sb.risk_penalty:
            breakdown_items.append(f"Risk:{sb.risk_penalty}")
        
        if breakdown_items:
            description_parts.append(f"*({' | '.join(breakdown_items)})*")
    
    description = "\n".join(description_parts)
    
    # Champs
    fields = []
    
    # Prix
    fields.append({
        "name": "💰 Prix",
        "value": annonce.format_prix(),
        "inline": True
    })
    
    # Kilométrage
    fields.append({
        "name": "🛣️ Kilométrage",
        "value": annonce.format_km(),
        "inline": True
    })
    
    # Année
    fields.append({
        "name": "📅 Année",
        "value": str(annonce.annee) if annonce.annee else "N/C",
        "inline": True
    })
    
    # Localisation
    loc = annonce.ville or ""
    if annonce.departement:
        loc += f" ({annonce.departement})" if loc else annonce.departement
    if loc:
        fields.append({
            "name": "📍 Localisation",
            "value": loc,
            "inline": True
        })
    
    # Carburant
    if annonce.carburant and annonce.carburant.value != "unknown":
        fields.append({
            "name": "⛽ Carburant",
            "value": annonce.carburant.value.capitalize(),
            "inline": True
        })
    
    # Vendeur
    if annonce.seller_type and annonce.seller_type.value != "unknown":
        fields.append({
            "name": "👤 Vendeur",
            "value": annonce.seller_type.value.capitalize(),
            "inline": True
        })
    
    # Marge estimée
    if annonce.margin_estimate_min or annonce.margin_estimate_max:
        margin = f"{annonce.margin_estimate_min:,} - {annonce.margin_estimate_max:,} €".replace(",", " ")
        if annonce.repair_cost_estimate:
            margin += f"\n*(réparations: ~{annonce.repair_cost_estimate:,}€)*".replace(",", " ")
        fields.append({
            "name": "💵 Marge potentielle",
            "value": margin,
            "inline": False
        })
    
    # Mots-clés opportunité
    if annonce.keywords_opportunite:
        fields.append({
            "name": "✅ Opportunités",
            "value": ", ".join(annonce.keywords_opportunite[:5]),
            "inline": True
        })
    
    # Mots-clés risque
    if annonce.keywords_risque:
        fields.append({
            "name": "⚠️ Risques",
            "value": ", ".join(annonce.keywords_risque[:5]),
            "inline": True
        })
    
    # Construire l'embed
    embed = {
        "title": title[:256],  # Limite Discord
        "description": description[:4096],
        "color": color,
        "fields": fields[:25],  # Limite Discord
        "url": annonce.url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": f"{annonce.source.value} • Score {annonce.score_total}/100"
        }
    }
    
    # Ajouter une image si disponible
    if annonce.images_urls:
        embed["thumbnail"] = {"url": annonce.images_urls[0]}
    
    return embed


async def send_batch_notification(annonces: list[Annonce]) -> int:
    """
    Envoie plusieurs notifications (avec throttling).
    
    Returns:
        Nombre de notifications envoyées avec succès
    """
    import asyncio
    
    settings = get_settings()
    delay = settings.notification.batch_delay_seconds
    
    sent = 0
    for annonce in annonces:
        success = await send_discord_notification(annonce)
        if success:
            sent += 1
        await asyncio.sleep(delay)
    
    return sent


async def send_update_notification(
    annonce: Annonce,
    old_prix: Optional[int] = None,
    old_score: Optional[int] = None
) -> bool:
    """
    Envoie une notification de mise à jour (prix baissé ou score monté).
    
    Args:
        annonce: L'annonce mise à jour
        old_prix: Ancien prix (si changé)
        old_score: Ancien score (si changé)
    
    Returns:
        True si notif envoyée
    """
    reasons = []
    
    # Prix baissé
    if old_prix and annonce.prix and annonce.prix < old_prix:
        diff = old_prix - annonce.prix
        pct = int((diff / old_prix) * 100)
        reasons.append(f"📉 Prix -{diff}€ (-{pct}%)")
    
    # Score monté
    if old_score and annonce.score_total > old_score:
        diff = annonce.score_total - old_score
        reasons.append(f"📈 Score +{diff}pts")
    
    if not reasons:
        return False
    
    reason_line = " | ".join(reasons)
    
    settings = get_settings()
    webhook_url = settings.discord.webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    
    if not webhook_url or not settings.discord.enabled:
        return False
    
    embed = _build_embed(annonce, reason=reason_line, is_update=True)
    
    payload = {
        "embeds": [embed],
        "username": "Voitures Bot",
        "content": f"🔄 **Mise à jour**: {reason_line}"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            return response.status_code in (200, 204)
    except Exception:
        return False


def should_notify(
    annonce: Annonce,
    existing: Optional[Annonce] = None,
    min_score: int = 60
) -> tuple[bool, str]:
    """
    Détermine si une annonce doit être notifiée.
    
    Returns:
        (should_notify, reason)
    """
    # Nouvelle annonce avec bon score
    if existing is None:
        if annonce.score_total >= min_score:
            return True, "new"
        return False, "score_too_low"
    
    # Annonce déjà notifiée et pas de changement significatif
    if existing.notified:
        # Prix baissé de plus de 5%
        if existing.prix and annonce.prix:
            if annonce.prix < existing.prix * 0.95:
                return True, "price_dropped"
        
        # Score monté significativement (>=10 pts)
        if annonce.score_total >= existing.score_total + 10:
            return True, "score_increased"
        
        return False, "already_notified"
    
    # Pas encore notifiée mais score suffisant
    if annonce.score_total >= min_score:
        return True, "score_threshold"
    
    return False, "score_too_low"
