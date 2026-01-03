"""
Notification Service - Gestion des notifications multi-canaux
"""

import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
import httpx

from models.annonce import Annonce
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN,
    TWILIO_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_FROM, PHONE_TO,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO,
    DISCORD_WEBHOOK_URL,
    SEUILS_ALERTE
)
from utils.logger import get_logger, log_notification, log_error

logger = get_logger(__name__)


class NotificationService:
    """Service de notifications multi-canaux"""
    
    def __init__(self):
        self.telegram_enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        self.pushover_enabled = bool(PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN)
        self.sms_enabled = bool(TWILIO_SID and TWILIO_AUTH_TOKEN and PHONE_TO)
        self.email_enabled = bool(SMTP_USER and SMTP_PASSWORD and EMAIL_TO)
        self.discord_enabled = bool(DISCORD_WEBHOOK_URL)
    
    async def notifier(self, annonce: Annonce) -> bool:
        """Envoie les notifications appropriées selon le score"""
        niveau = annonce.niveau_alerte
        success = False
        
        try:
            if niveau == "urgent":
                # Tous les canaux
                results = await asyncio.gather(
                    self.send_discord(annonce),
                    self.send_telegram(annonce),
                    self.send_pushover(annonce, priority=1),
                    self.send_sms(annonce),
                    return_exceptions=True
                )
                success = any(r is True for r in results)
                
            elif niveau == "interessant":
                # Push + Discord
                results = await asyncio.gather(
                    self.send_discord(annonce),
                    self.send_telegram(annonce),
                    self.send_pushover(annonce),
                    return_exceptions=True
                )
                success = any(r is True for r in results)
                
            elif niveau == "surveiller":
                # Discord + Email
                results = await asyncio.gather(
                    self.send_discord(annonce),
                    self.send_email(annonce),
                    return_exceptions=True
                )
                success = any(r is True for r in results)
            
            if success:
                log_notification(annonce, niveau)
            
        except Exception as e:
            log_error(f"Erreur notification pour {annonce.url}", e)
        
        return success
    
    async def send_telegram(self, annonce: Annonce) -> bool:
        """Envoie une notification Telegram"""
        if not self.telegram_enabled:
            return False
        
        try:
            message = annonce.format_notification()
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                })
                
                if response.status_code == 200:
                    logger.debug(f"Telegram envoyé: {annonce.titre}")
                    return True
                else:
                    log_error(f"Telegram erreur: {response.text}")
                    return False
                    
        except Exception as e:
            log_error("Erreur envoi Telegram", e)
            return False
    
    async def send_pushover(self, annonce: Annonce, priority: int = 0) -> bool:
        """Envoie une notification Pushover"""
        if not self.pushover_enabled:
            return False
        
        try:
            titre = f"{annonce.emoji_alerte} {annonce.marque} {annonce.modele} - {annonce.prix}€"
            message = (
                f"Score: {annonce.score_rentabilite}/100\n"
                f"Km: {annonce.kilometrage:,} km\n" if annonce.kilometrage else ""
                f"Lieu: {annonce.ville} ({annonce.departement})\n" if annonce.ville else ""
                f"Marge: {annonce.marge_estimee_min}€-{annonce.marge_estimee_max}€"
                if annonce.marge_estimee_min else ""
            )
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.pushover.net/1/messages.json",
                    data={
                        "token": PUSHOVER_API_TOKEN,
                        "user": PUSHOVER_USER_KEY,
                        "title": titre,
                        "message": message,
                        "url": annonce.url,
                        "url_title": "Voir l'annonce",
                        "priority": priority,
                        "sound": "cashregister" if priority >= 1 else "pushover"
                    }
                )
                
                if response.status_code == 200:
                    logger.debug(f"Pushover envoyé: {annonce.titre}")
                    return True
                else:
                    log_error(f"Pushover erreur: {response.text}")
                    return False
                    
        except Exception as e:
            log_error("Erreur envoi Pushover", e)
            return False
    
    async def send_sms(self, annonce: Annonce) -> bool:
        """Envoie un SMS via Twilio"""
        if not self.sms_enabled:
            return False
        
        try:
            message = (
                f"🚗 ALERTE VOITURE {annonce.score_rentabilite}/100\n"
                f"{annonce.marque} {annonce.modele}\n"
                f"{annonce.prix}€ - {annonce.ville}\n"
                f"{annonce.url}"
            )
            
            # Twilio REST API
            url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    auth=(TWILIO_SID, TWILIO_AUTH_TOKEN),
                    data={
                        "From": TWILIO_PHONE_FROM,
                        "To": PHONE_TO,
                        "Body": message
                    }
                )
                
                if response.status_code in [200, 201]:
                    logger.debug(f"SMS envoyé: {annonce.titre}")
                    return True
                else:
                    log_error(f"Twilio erreur: {response.text}")
                    return False
                    
        except Exception as e:
            log_error("Erreur envoi SMS", e)
            return False
    
    async def send_email(self, annonce: Annonce) -> bool:
        """Envoie un email"""
        if not self.email_enabled:
            return False
        
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"{annonce.emoji_alerte} {annonce.marque} {annonce.modele} - {annonce.prix}€ - Score {annonce.score_rentabilite}"
            msg["From"] = SMTP_USER
            msg["To"] = EMAIL_TO
            
            # Version texte
            text = annonce.format_notification()
            
            # Version HTML
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>{annonce.emoji_alerte} {annonce.marque} {annonce.modele}</h2>
                <p><strong>Prix:</strong> {annonce.prix:,}€</p>
                <p><strong>Kilométrage:</strong> {annonce.kilometrage:,} km</p>
                <p><strong>Année:</strong> {annonce.annee}</p>
                <p><strong>Lieu:</strong> {annonce.ville} ({annonce.departement})</p>
                <p><strong>Score:</strong> {annonce.score_rentabilite}/100</p>
                {"<p><strong>Mots-clés:</strong> " + ", ".join(annonce.mots_cles_detectes) + "</p>" if annonce.mots_cles_detectes else ""}
                <p><strong>Marge estimée:</strong> {annonce.marge_estimee_min}€ - {annonce.marge_estimee_max}€</p>
                <p><a href="{annonce.url}" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Voir l'annonce</a></p>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(text, "plain"))
            msg.attach(MIMEText(html, "html"))
            
            # Envoi synchrone (dans un thread)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_email_sync, msg)
            
            logger.debug(f"Email envoyé: {annonce.titre}")
            return True
            
        except Exception as e:
            log_error("Erreur envoi Email", e)
            return False
    
    def _send_email_sync(self, msg):
        """Envoi email synchrone"""
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    
    async def send_recap(self, annonces: List[Annonce]) -> bool:
        """Envoie un récapitulatif des annonces"""
        if not annonces:
            return True
        
        try:
            message = f"📊 RÉCAPITULATIF - {len(annonces)} annonces\n\n"
            
            for annonce in annonces[:10]:  # Max 10 annonces
                message += (
                    f"{annonce.emoji_alerte} {annonce.marque} {annonce.modele} - "
                    f"{annonce.prix}€ - Score: {annonce.score_rentabilite}\n"
                )
            
            if len(annonces) > 10:
                message += f"\n... et {len(annonces) - 10} autres"
            
            # Envoyer via Telegram
            if self.telegram_enabled:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                async with httpx.AsyncClient() as client:
                    await client.post(url, json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": message
                    })
            
            return True
            
        except Exception as e:
            log_error("Erreur envoi récap", e)
            return False
    
    async def send_discord(self, annonce: Annonce) -> bool:
        """Envoie une notification Discord via webhook"""
        if not self.discord_enabled:
            return False
        
        try:
            # Couleur selon le niveau d'alerte
            colors = {
                "urgent": 0xFF0000,      # Rouge
                "interessant": 0xFFA500,  # Orange
                "surveiller": 0xFFFF00,   # Jaune
                "archive": 0x808080       # Gris
            }
            color = colors.get(annonce.niveau_alerte, 0x808080)
            
            # Construire l'embed Discord
            embed = {
                "title": f"{annonce.emoji_alerte} {annonce.marque} {annonce.modele} - Score: {annonce.score_rentabilite}/100",
                "url": annonce.url,
                "color": color,
                "fields": [
                    {"name": "💰 Prix", "value": f"{annonce.prix:,}€" if annonce.prix else "N/A", "inline": True},
                    {"name": "🛣️ Kilométrage", "value": f"{annonce.kilometrage:,} km" if annonce.kilometrage else "N/A", "inline": True},
                    {"name": "📅 Année", "value": str(annonce.annee) if annonce.annee else "N/A", "inline": True},
                    {"name": "📍 Localisation", "value": f"{annonce.ville} ({annonce.departement})" if annonce.ville else "N/A", "inline": True},
                    {"name": "⛽ Carburant", "value": annonce.carburant or "N/A", "inline": True},
                    {"name": "👤 Vendeur", "value": annonce.type_vendeur or "particulier", "inline": True},
                ],
                "footer": {"text": f"Source: {annonce.source}"},
            }
            
            # Ajouter la marge estimée si disponible
            if annonce.marge_estimee_min and annonce.marge_estimee_max:
                embed["fields"].append({
                    "name": "💵 Marge potentielle",
                    "value": f"{annonce.marge_estimee_min}€ - {annonce.marge_estimee_max}€",
                    "inline": True
                })
            
            # Ajouter les mots-clés si détectés
            if annonce.mots_cles_detectes:
                embed["fields"].append({
                    "name": "🔑 Mots-clés",
                    "value": ", ".join(annonce.mots_cles_detectes[:5]),
                    "inline": False
                })
            
            # Ajouter une image si disponible
            if annonce.images_urls and len(annonce.images_urls) > 0:
                embed["thumbnail"] = {"url": annonce.images_urls[0]}
            
            # Payload Discord
            payload = {
                "username": "🚗 Bot Voitures",
                "embeds": [embed]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    DISCORD_WEBHOOK_URL,
                    json=payload
                )
                
                if response.status_code in [200, 204]:
                    logger.debug(f"Discord envoyé: {annonce.titre}")
                    return True
                else:
                    log_error(f"Discord erreur {response.status_code}: {response.text}")
                    return False
                    
        except Exception as e:
            log_error("Erreur envoi Discord", e)
            return False
    
    def get_status(self) -> dict:
        """Retourne le statut des canaux de notification"""
        return {
            "discord": self.discord_enabled,
            "telegram": self.telegram_enabled,
            "pushover": self.pushover_enabled,
            "sms": self.sms_enabled,
            "email": self.email_enabled
        }
