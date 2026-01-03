"""
Settings - Configuration centralisée via pydantic-settings
Charge depuis .env et variables d'environnement
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Chemins de base
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"


class DatabaseSettings(BaseSettings):
    """Configuration base de données"""
    model_config = SettingsConfigDict(env_prefix="DB_")
    
    url: str = Field(default=f"sqlite:///{DATA_DIR}/annonces.db")
    echo: bool = False


class ProxySettings(BaseSettings):
    """Configuration proxies"""
    model_config = SettingsConfigDict(env_prefix="PROXY_")
    
    enabled: bool = True
    rotation_enabled: bool = True
    # Liste chargée depuis fichier ou env
    urls: list[str] = Field(default_factory=list)


class DiscordSettings(BaseSettings):
    """Configuration Discord"""
    model_config = SettingsConfigDict(
        env_prefix="DISCORD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    webhook_url: Optional[str] = None
    enabled: bool = True
    embed_color_urgent: int = 0xFF0000      # Rouge
    embed_color_interessant: int = 0xFF8C00  # Orange
    embed_color_surveiller: int = 0xFFD700   # Jaune
    embed_color_archive: int = 0x808080      # Gris


class TelegramSettings(BaseSettings):
    """Configuration Telegram"""
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")
    
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    enabled: bool = False


class EmailSettings(BaseSettings):
    """Configuration Email"""
    model_config = SettingsConfigDict(env_prefix="EMAIL_")
    
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    from_addr: Optional[str] = None
    to_addr: Optional[str] = None
    enabled: bool = False


class SmsSettings(BaseSettings):
    """Configuration SMS (Twilio)"""
    model_config = SettingsConfigDict(env_prefix="TWILIO_")
    
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    enabled: bool = False


class ScrapingSettings(BaseSettings):
    """Configuration scraping"""
    model_config = SettingsConfigDict(env_prefix="SCRAPING_")
    
    # Délais entre requêtes (secondes)
    min_delay: float = 2.0
    max_delay: float = 5.0
    
    # Circuit breaker
    error_threshold: int = 10
    error_window_seconds: int = 300  # 5 minutes
    cooldown_seconds: int = 900      # 15 minutes pause si trop d'erreurs
    
    # Timeouts
    request_timeout: int = 30
    
    # Score minimum pour récupérer les détails
    detail_score_threshold: int = 40
    
    # Mode debug (sauvegarde HTML brut)
    save_raw_html: bool = False


class NotificationSettings(BaseSettings):
    """Configuration notifications"""
    model_config = SettingsConfigDict(env_prefix="NOTIF_")
    
    # Seuils d'alerte
    threshold_urgent: int = 80
    threshold_interessant: int = 60
    threshold_surveiller: int = 40
    
    # Cooldown entre notifications pour même annonce (minutes)
    cooldown_minutes: int = 60
    
    # Groupement max
    batch_size: int = 5
    batch_delay_seconds: int = 2


class Settings(BaseSettings):
    """Configuration principale"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # Mode
    debug: bool = False
    log_level: str = "INFO"
    
    # Sous-configurations
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    sms: SmsSettings = Field(default_factory=SmsSettings)
    scraping: ScrapingSettings = Field(default_factory=ScrapingSettings)
    notification: NotificationSettings = Field(default_factory=NotificationSettings)


# Instance globale (singleton)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Retourne l'instance des settings (lazy loading)"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
