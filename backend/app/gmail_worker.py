from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_storage import get_document_storage
from app.services.document_text_extractor import get_document_text_extractor
from app.services.gmail_client import GmailApiError, GmailClient
from app.services.gmail_ingestion import poll_gmail_once

logger = logging.getLogger("hic.gmail_worker")


async def run_worker() -> None:
    settings = get_settings()
    if not settings.gmail_ingestion_enabled:
        logger.info("Gmail ingestion is disabled; worker is exiting")
        return
    assert settings.gmail_client_id is not None
    assert settings.gmail_client_secret is not None
    assert settings.gmail_refresh_token is not None
    client = GmailClient(
        client_id=settings.gmail_client_id.get_secret_value(),
        client_secret=settings.gmail_client_secret.get_secret_value(),
        refresh_token=settings.gmail_refresh_token.get_secret_value(),
    )
    storage = get_document_storage(settings)
    extractor = get_document_text_extractor()
    chunker = DeterministicCharacterChunker()
    try:
        while True:
            try:
                result = await poll_gmail_once(
                    settings=settings,
                    client=client,
                    session_factory=SessionLocal,
                    storage=storage,
                    extractor=extractor,
                    chunker=chunker,
                )
                logger.info(
                    "Gmail poll completed: messages=%d imported=%d duplicates=%d "
                    "rejected=%d failed=%d skipped=%d",
                    result.messages_found,
                    result.attachments_imported,
                    result.attachments_duplicate,
                    result.attachments_rejected,
                    result.attachments_failed,
                    result.attachments_skipped,
                )
            except GmailApiError as exc:
                logger.warning("Gmail poll failed with code %s", exc.code)
            except Exception:
                logger.error("Gmail poll failed unexpectedly; details were suppressed for privacy")
            await asyncio.sleep(settings.gmail_poll_interval_seconds)
    finally:
        client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
