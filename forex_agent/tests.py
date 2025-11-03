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

# --- Local Imports ---
# Import the AI services and the database model we created.
from .ai_services import ai_processor, embedding_generator
from .models import KnowledgeArticle

# Get a logger instance for this module, as configured in settings.py
logger = logging.getLogger('forex_agent')

# ==============================================================================
# 1. CORE PROCESSING SUB-TASK
# ==============================================================================
# This is a generic, reusable task that forms the backbone of our data pipeline.
# Its only job is to take raw content, process it through our AI services,
# and save the final, high-quality result to the database.
# By keeping it separate, our system becomes more modular and easier to debug.
# ==============================================================================
@shared_task(
    name="process_and_store_content_task",
    bind=True,
    autoretry_for=(Exception,), # Automatically retry on any exception.
    retry_kwargs={'max_retries': 3, 'countdown': 90} # Retry up to 3 times, with a 90-second delay.
)
def process_and_store_content_task(self, source_url: str, title: str, raw_content: str, content_type: str, published_at_str: str | int = None):
    """
    A robust, retryable Celery task that processes a single piece of content.
    This task is designed to be called by other fetching/scraping tasks.
    """
    try:
        logger.info(f"Starting to process content for URL: {source_url}")

        # --- Step 1: Check for Duplicates ---
        # This is a crucial optimization to prevent re-processing and re-hitting paid APIs for content we already have.
        if KnowledgeArticle.objects.filter(source_url=source_url).exists():
            logger.warning(f"Content from URL {source_url} already exists. Skipping.")
            return f"Skipped: Duplicate content for {title}"

        # --- Step 2: AI Content Articulation (using Gemini) ---
        # This is where we transform raw data into beginner-friendly knowledge.
        logger.debug(f"Calling AI processor for '{title}'...")
        processed_text = ai_processor.clean_and_format_text(raw_content, content_type=content_type)
        if not processed_text or "could not be processed" in processed_text.lower():
            logger.error(f"AI processing failed for URL {source_url}. Content was empty or blocked.")
            return f"Failed: AI processing for {title}"

        # --- Step 3: Vector Embedding Generation (using OpenAI) ---
        # This creates the vector needed for our semantic search system.
        logger.debug(f"Generating embedding for '{title}'...")
        embedding_vector = embedding_generator.create_embedding(processed_text)
        if embedding_vector is None:
            logger.error(f"Embedding generation failed for URL {source_url}.")
            # We raise an exception to trigger Celery's retry mechanism.
            raise ValueError(f"Embedding generation failed for {title}")

        # --- Step 4: Robust Timestamp Parsing ---
        # This handles the different date formats from our various sources.
        published_at_dt = None
        if published_at_str:
            try:
                if isinstance(published_at_str, int): # Finnhub provides a UNIX timestamp (integer)
                    published_at_dt = datetime.fromtimestamp(published_at_str, tz=ZoneInfo("UTC"))
                else: # Alpha Vantage provides a string 'YYYYMMDDTHHMMSS'
                    published_at_dt = datetime.strptime(published_at_str, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo("UTC"))
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse timestamp '{published_at_str}' for URL {source_url}. Error: {e}")

        # --- Step 5: Save to Database ---
        logger.debug(f"Saving article '{title}' to database...")
        KnowledgeArticle.objects.create(
            source_url=source_url,
            title=title,
            processed_content=processed_text,
            embedding=embedding_vector,
            content_type=content_type,
            published_at=published_at_dt,
        )

        logger.info(f"Successfully processed and stored content from: {source_url}")
        return f"Success: Stored {title}"

    except Exception as exc:
        logger.critical(f"A critical error occurred in process_and_store_content for URL {source_url}: {exc}", exc_info=True)
        # Re-raise the exception. Celery's `autoretry_for` will catch it and schedule a retry.
        raise exc




# ==============================================================================
# 2. SCHEDULED NEWS FETCHING TASK (Main Task)
# ==============================================================================
# This is a primary scheduled task. It uses `asyncio` and `httpx` to fetch data
# from two different news APIs concurrently for maximum efficiency. It then
# dispatches the content to our generic processing task.
# ==============================================================================
@shared_task(name="fetch_and_process_market_news")
def fetch_and_process_market_news():
    """
    Fetches market news concurrently from Finnhub and Alpha Vantage, then
    dispatches processing tasks for each article. Runs on a schedule.
    """
    logger.info("--- Starting Scheduled Task: Fetch and Process Market News ---")
    try:
        asyncio.run(fetch_news_concurrently())
    except Exception as e:
        logger.critical(f"Critical error in the main news fetching asyncio runner: {e}", exc_info=True)

async def fetch_news_concurrently():
    """Asynchronous helper function to perform concurrent API requests."""
    finnhub_key = config('FINNHUB_API_KEY', default=None)
    alpha_vantage_key = config('ALPHA_VANTAGE_API_KEY', default=None)

    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        if finnhub_key:
            url = f"https://finnhub.io/api/v1/news?category=forex&token={finnhub_key}"
            tasks.append(client.get(url))
        else:
            logger.warning("FINNHUB_API_KEY is not configured. Skipping Finnhub fetch.")

        if alpha_vantage_key:
            url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=financial_markets&apikey={alpha_vantage_key}"
            tasks.append(client.get(url))
        else:
            logger.warning("ALPHA_VANTAGE_API_KEY is not configured. Skipping Alpha Vantage fetch.")

        if not tasks:
            logger.error("No news API keys are available. Terminating news fetch task.")
            return

        # `return_exceptions=True` is crucial for resilience.
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # --- Process Finnhub Response ---
        try:
            finnhub_response = responses[0]
            if isinstance(finnhub_response, httpx.Response):
                finnhub_response.raise_for_status()
                for article in finnhub_response.json()[:10]: # Process top 10
                    if all(k in article for k in ['url', 'headline', 'summary']):
                        process_and_store_content_task.delay(
                            source_url=article['url'], title=article['headline'], raw_content=article['summary'],
                            content_type='news', published_at_str=article.get('datetime')
                        )
            elif isinstance(finnhub_response, Exception):
                logger.error(f"Failed to fetch from Finnhub: {finnhub_response}")
        except Exception as e:
            logger.error(f"Error processing Finnhub response: {e}")

        # --- Process Alpha Vantage Response ---
        try:
            alpha_vantage_response = responses[1]
            if isinstance(alpha_vantage_response, httpx.Response):
                alpha_vantage_response.raise_for_status()
                for article in alpha_vantage_response.json().get('feed', [])[:10]: # Process top 10
                    if all(k in article for k in ['url', 'title', 'summary']):
                        process_and_store_content_task.delay(
                            source_url=article['url'], title=article['title'], raw_content=article['summary'],
                            content_type='news', published_at_str=article.get('time_published')
                        )
            elif isinstance(alpha_vantage_response, Exception):
                logger.error(f"Failed to fetch from Alpha Vantage: {alpha_vantage_response}")
        except Exception as e:
            logger.error(f"Error processing Alpha Vantage response: {e}")

# ==============================================================================
# 3. SCHEDULED WEB SCRAPING TASK (Main Task & Sub-Task)
# ==============================================================================
# This section uses a two-task approach for scraping:
# 1. `scrape_babypips_for_links`: Runs on a schedule to find article links.
# 2. `process_scraped_page`: A sub-task that handles the scraping of one single page.
# This makes the process more resilient; a failure on one page won't stop the others.
# ==============================================================================
@shared_task(name="scrape_and_process_educational_content")
def scrape_babypips_for_links():
    """
    Scheduled task that scrapes the main BabyPips 'learn' page to find new lesson URLs,
    then dispatches a sub-task for each URL.
    """
    START_URL = "https://www.babypips.com/learn/forex"
    BASE_URL = "https://www.babypips.com"
    logger.info(f"--- Starting Scheduled Task: Scrape BabyPips for Links from {START_URL} ---")

    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            response = client.get(START_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # This selector specifically targets the links within the course list.
            lesson_links = soup.select('a[href^="/learn/forex/"]')
            unique_urls = {f"{BASE_URL}{link.get('href')}" for link in lesson_links if link.get('href')}

            if not unique_urls:
                logger.warning(f"No lesson links found at {START_URL}. The website structure may have changed.")
                return

            logger.info(f"Found {len(unique_urls)} unique lesson links. Dispatching processing tasks...")
            
            # Dispatch a sub-task for each unique URL found.
            for url in list(unique_urls)[:10]: # Limit to 10 new pages per run to be respectful.
                process_scraped_page.delay(url)

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error while scraping {START_URL}: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Network error while scraping {START_URL}: {e}")
    except Exception as e:
        logger.critical(f"A critical error occurred during the main scraping task: {e}", exc_info=True)

@shared_task(rate_limit='15/m') # Rate limit scraping to 15 pages per minute.
def process_scraped_page(url: str):
    """A sub-task to scrape a single page and dispatch it to the content processor."""
    try:
        logger.debug(f"Processing scraped page: {url}")
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_element = soup.find('h1')
            # This selector targets the main content area of a BabyPips lesson.
            content_element = soup.find('article')

            if title_element and content_element:
                title = title_element.get_text(strip=True)
                raw_content = content_element.get_text(strip=True, separator='\n')
                
                # Hand off the extracted content to the main processing pipeline.
                process_and_store_content_task.delay(
                    source_url=url,
                    title=title,
                    raw_content=raw_content,
                    content_type='article'
                )
            else:
                logger.warning(f"Could not extract title or content from {url}. Page structure might have changed.")

    except Exception as e:
        logger.error(f"Failed to process individual scraped page {url}: {e}", exc_info=True)