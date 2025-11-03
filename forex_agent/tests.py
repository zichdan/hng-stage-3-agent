from django.test import TestCase

# Create your tests here.
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup
from celery import shared_task
from decouple import config
from django.conf import settings # Import Django's settings to access our custom config

# --- Local Imports ---
from .ai_services import ai_processor, embedding_generator
from .models import KnowledgeArticle

# Get a logger instance for this module, as configured in settings.py.
logger = logging.getLogger('forex_agent')

# ==============================================================================
# 1. CORE PROCESSING SUB-TASK (The Final Step in the Pipeline)
# ==============================================================================
# This is a generic, reusable task that handles the most intensive work.
# It's called by other tasks and is responsible for AI processing and database insertion.
# Its retry logic ensures that transient API or network failures are handled gracefully.
# ==============================================================================
@shared_task(
    name="process_and_store_content",
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 120}, # Retry up to 3 times, with a 2-minute delay
    acks_late=True
)
def process_and_store_content(self, source_url: str, title: str, raw_content: str, content_type: str, published_at_str: str | int = None):
    """
    A robust, retryable task that forms the core of our knowledge pipeline.
    It takes raw data, processes it with AI, generates an embedding, and saves it to the database.
    """
    try:
        logger.info(f"Starting to process content for URL: {source_url}")

        # --- Step 1: Final Duplicate Check ---
        # Although the dispatcher tasks might check, this is a final safeguard.
        if KnowledgeArticle.objects.filter(source_url=source_url).exists():
            logger.warning(f"Content from {source_url} already exists. Skipping.")
            return f"Skipped: Duplicate content for '{title}'"

        # --- Step 2: AI Content Articulation (Gemini) ---
        processed_text = ai_processor.clean_and_format_text(raw_content, content_type=content_type)
        if not processed_text or "could not be processed" in processed_text.lower():
            logger.error(f"AI processing failed for '{title}'. Aborting.")
            return f"Failed: AI processing for '{title}'"

        # --- Step 3: Vector Embedding Generation (OpenAI) ---
        embedding_vector = embedding_generator.create_embedding(processed_text)
        if embedding_vector is None:
            logger.error(f"Embedding generation failed for '{title}'. This task will be retried.")
            raise ValueError("Embedding generation returned None, triggering retry.")

        # --- Step 4: Robust Datetime Parsing ---
        published_at_dt = None
        if published_at_str:
            try:
                if isinstance(published_at_str, int): # Handles UNIX timestamp from Finnhub
                    published_at_dt = datetime.fromtimestamp(published_at_str, tz=ZoneInfo("UTC"))
                else: # Handles 'YYYYMMDDTHHMMSS' from Alpha Vantage
                    published_at_dt = datetime.strptime(published_at_str, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo("UTC"))
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse timestamp '{published_at_str}' for '{title}'. Error: {e}")

        # --- Step 5: Save to Database ---
        KnowledgeArticle.objects.create(
            source_url=source_url, title=title, processed_content=processed_text,
            embedding=embedding_vector, content_type=content_type, published_at=published_at_dt,
        )
        logger.info(f"Successfully processed and stored: '{title}'")
        return f"Success: Stored '{title}'"

    except Exception as exc:
        logger.critical(f"A critical error occurred in the processing pipeline for {source_url}: {exc}", exc_info=True)
        raise exc # Re-raise to trigger Celery's autoretry mechanism.

# ==============================================================================
# 2. ORCHESTRATOR TASK (The Main Scheduled Task)
# ==============================================================================
# This is the single task triggered by Celery Beat. It acts as a manager,
# dispatching the specific worker tasks to do the heavy lifting.
# ==============================================================================
@shared_task(name="forex_agent.tasks.scheduled_knowledge_update")
def scheduled_knowledge_update():
    """
    The main orchestrator task, triggered by Celery Beat. It dispatches
    the news fetching and educational content scraping tasks to run in parallel.
    """
    logger.info("--- Starting Bi-Hourly Knowledge Update Cycle ---")
    fetch_and_process_market_news.delay()
    scrape_babypips_for_links.delay()
    logger.info("--- Dispatched all knowledge update tasks. Cycle complete. ---")

# ==============================================================================
# 3. WORKER TASKS (The "Doers")
# ==============================================================================
# These tasks perform the actual I/O-bound work of fetching and scraping.
# ==============================================================================
@shared_task(name="forex_agent.tasks.fetch_and_process_market_news")
def fetch_and_process_market_news():
    """Worker Task: Fetches news from APIs and dispatches to the processing pipeline."""
    logger.info("Starting sub-task: fetch_and_process_market_news")
    try:
        asyncio.run(fetch_news_concurrently())
    except Exception as e:
        logger.critical(f"Critical error in the news fetching asyncio runner: {e}", exc_info=True)

async def fetch_news_concurrently():
    """Asynchronous helper for concurrent API requests."""
    finnhub_key = config('FINNHUB_API_KEY', default=None)
    alpha_vantage_key = config('ALPHA_VANTAGE_API_KEY', default=None)

    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        if finnhub_key: tasks.append(client.get(f"https://finnhub.io/api/v1/news?category=forex&token={finnhub_key}"))
        if alpha_vantage_key: tasks.append(client.get(f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=financial_markets&apikey={alpha_vantage_key}"))
        
        if not tasks:
            logger.error("No news API keys configured. Terminating news fetch.")
            return

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process Finnhub
        if len(responses) > 0 and isinstance(responses[0], httpx.Response):
            if responses[0].status_code == 200:
                for article in responses[0].json()[:10]:
                    if all(k in article for k in ['url', 'headline', 'summary']):
                        process_and_store_content.delay(
                            source_url=article['url'], title=article['headline'], raw_content=article['summary'],
                            content_type='news', published_at_str=article.get('datetime')
                        )
            else: logger.error(f"Finnhub API returned status {responses[0].status_code}")
        elif len(responses) > 0: logger.error(f"Failed to fetch from Finnhub: {responses[0]}")

        # Process Alpha Vantage
        if len(responses) > 1 and isinstance(responses[1], httpx.Response):
            if responses[1].status_code == 200:
                for article in responses[1].json().get('feed', [])[:10]:
                    if all(k in article for k in ['url', 'title', 'summary']):
                        process_and_store_content.delay(
                            source_url=article['url'], title=article['title'], raw_content=article['summary'],
                            content_type='news', published_at_str=article.get('time_published')
                        )
            else: logger.error(f"Alpha Vantage API returned status {responses[1].status_code}")
        elif len(responses) > 1: logger.error(f"Failed to fetch from Alpha Vantage: {responses[1]}")

@shared_task(name="forex_agent.tasks.scrape_babypips_for_links")
def scrape_babypips_for_links():
    """Dispatcher Task: Finds new lesson URLs from BabyPips and dispatches worker tasks."""
    try:
        scraper_config = settings.SCRAPER_CONFIG["BABYPIPS"]
        logger.info(f"--- Starting Task: Scrape BabyPips Links from {scraper_config['START_URL']} ---")

        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            response = client.get(scraper_config["START_URL"])
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links_on_page = soup.select(scraper_config["LINK_SELECTOR"])
            all_urls = {f"{scraper_config['BASE_URL']}{link.get('href')}" for link in links_on_page if link.get('href')}

            if not all_urls:
                logger.warning(f"No links found at {scraper_config['START_URL']} using selector '{scraper_config['LINK_SELECTOR']}'.")
                return

            existing_urls = set(KnowledgeArticle.objects.values_list('source_url', flat=True))
            new_urls = all_urls - existing_urls

            if not new_urls:
                logger.info("No new lesson URLs found. Content is up to date.")
                return

            logger.info(f"Found {len(new_urls)} new lesson links. Dispatching workers...")
            for url in list(new_urls)[:scraper_config["RESPECTFUL_LIMIT"]]:
                process_scraped_page.delay(url)
    except Exception as e:
        logger.critical(f"Critical error in main scraping task: {e}", exc_info=True)

@shared_task(
    name="forex_agent.tasks.process_scraped_page",
    rate_limit='15/m', # Respectful rate limit
    autoretry_for=(httpx.RequestError, httpx.HTTPStatusError),
    retry_backoff=True,
    retry_kwargs={'max_retries': 3}
)
def process_scraped_page(url: str):
    """Worker Sub-task: Scrapes a single page and dispatches it to the final processing pipeline."""
    scraper_config = settings.SCRAPER_CONFIG["BABYPIPS"]
    try:
        logger.debug(f"Processing scraped page: {url}")
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = soup.select_one(scraper_config["TITLE_SELECTOR"])
            content = soup.select_one(scraper_config["CONTENT_SELECTOR"])

            if title and content:
                process_and_store_content.delay(
                    source_url=url, title=title.get_text(strip=True),
                    raw_content=content.get_text(strip=True, separator='\n'),
                    content_type='article'
                )
            else:
                logger.warning(f"Could not extract title/content from {url}. Selectors might need updating.")
    except Exception as e:
        logger.error(f"Failed to process individual page {url}: {e}", exc_info=True)
        raise e # Re-raise to allow Celery to handle retries