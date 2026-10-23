from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    youtube_client_secrets_file: Path = Path("oauth_client.json")
    youtube_token_file: Path = Path("token.json")
    youtube_api_key: str | None = None
    youtube_channel_id: str | None = None
    analytics_days: int = 30
    trend_region: str = "IN"
    trend_query: str = "technology science psychology culture nature discovery"
    instagram_access_token: str | None = None
    instagram_business_account_id: str | None = None
    publish_mode: str = "review"
    publish_at_hour_ist: int = 18
    daily_target: int = 1
    max_regeneration_attempts: int = 3
    min_review_score: int = 8
    channel_niche: str = "Science explained through surprising everyday questions"
    channel_voice: str = "Curious, precise, and conversational. Never sensational."
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")

    def validate_production(self) -> list[str]:
        missing = []
        if not (self.gemini_api_key or self.groq_api_key):
            missing.append("GEMINI_API_KEY or GROQ_API_KEY")
        if not (self.telegram_bot_token and self.telegram_chat_id):
            missing.append("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        if self.publish_mode not in {"review", "schedule"}:
            missing.append("PUBLISH_MODE must be review or schedule")
        if self.publish_mode == "schedule" and not self.youtube_token_file.exists():
            missing.append("YouTube OAuth token; run authorize-youtube")
        return missing
