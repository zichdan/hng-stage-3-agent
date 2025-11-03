# forex_agent/tasks.py
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup
from celery import shared_task
from decouple import config

# --- Local Imports ---
# Import the AI services and the database model we created in previous steps.
from .ai_services import ai_processor, embedding_generator
from .models import ProcessedContent

# Get a logger instance for this module, as configured in settings.py.
# This allows us to see detailed, app-specific logs during execution.
logger = logging.getLogger('forex_agent')

# ==============================================================================
# 1. GENERIC CONTENT PROCESSING SUB-TASK
# ==============================================================================
# This is a generic, reusable task. Its only job is to take raw content,
# process it through our AI services, and save it to the database. By keeping
# it separate, we make our system more modular and easier to debug. This is the
# final step in our data processing pipeline.
# ==============================================================================
@shared_task(
    bind=True,  # Binds the task instance to `self`, allowing for retries
    autoretry_for=(Exception,),  # Automatically retry this task on ANY exception
    retry_kwargs={'max_retries': 3, 'countdown': 90}, # Retry up to 3 times, with a 90-second delay.
    acks_late=True # Ensures the task is only acknowledged after it completes successfully
)
def process_and_store_content(self, source_url: str, title: str, raw_content: str, content_type: str, published_at_str: str | int = None):
    """
    A robust, retryable Celery task that forms the core of our knowledge pipeline.
    It takes raw data, processes it with AI, generates an embedding, and saves it to the database.
    """
    try:
        logger.info(f"Starting to process content for URL: {source_url}")

        # --- Step 1: Check for Duplicates ---
        # This prevents us from re-processing and re-hitting AI APIs for content we already have.
        # It's a critical step for efficiency and cost-saving.
        if ProcessedContent.objects.filter(source_url=source_url).exists():
            logger.warning(f"Content from URL {source_url} already exists in the database. Skipping.")
            return f"Skipped: {source_url} already exists."


        # --- Step 2: AI-Powered Content Processing (using Gemini) ---
        # Use the Gemini service to clean, articulate and transform raw data into beginner-friendly knowledge.
        logger.debug(f"Calling AI processor for '{title}'...")
        processed_text = ai_processor.clean_and_format_text(raw_content, content_type=content_type)
        if not processed_text or "could not be processed" in processed_text:
            logger.error(f"AI processing failed or returned empty for '{title}'. Aborting storage.")
            return f"AI Processing Failed: {title}"


        # --- Step 3: Vector Embedding Generation (using OpenAI) ---
        # Use the OpenAI service to create a vector embedding for the cleaned text needed for our semantic search system.
        logger.debug(f"Generating embedding for '{title}'...")
        embedding_vector = embedding_generator.create_embedding(processed_text)
        if embedding_vector is None:
            # If embedding fails, we raise an exception. Because of `autoretry_for=(Exception,)`,
            # Celery will automatically catch this and retry the task later.
            logger.error(f"Failed to generate embedding for '{title}'. This task will be retried.")
            raise ValueError(f"Embedding generation failed for {title}")


        # --- Step 4: Prepare Robust Datetime Timestamp Parsing ---
        # This handles the different date formats from our various sources.
        published_at_dt = None
        if published_at_str:
            # Handle different timestamp formats from APIs:
            try:
                if isinstance(published_at_str, int):
                    # Finnhub provides a UNIX timestamp (integer).
                    published_at_dt = datetime.fromtimestamp(published_at_str, tz=ZoneInfo("UTC"))
                elif isinstance(published_at_str, str):
                    # Alpha Vantage provides an ISO-like format string 'YYYYMMDDTHHMMSS'.
                    published_at_dt = datetime.strptime(published_at_str, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo("UTC"))
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse timestamp '{published_at_str}' for URL {source_url}. Error: {e}")
        

        # --- Step 5: Save to Database ---
        logger.debug(f"Saving article '{title}' to database...")
        ProcessedContent.objects.create(
            source_url=source_url,
            title=title,
            processed_content=processed_text,
            embedding=embedding_vector,
            content_type=content_type,
            published_at=published_at_dt,
        )

        logger.info(f"Successfully processed and stored content from: {source_url}")
        return f"Successfully processed: {source_url}"

    except Exception as exc:
        # A final, robust catch-all. This will log the error and then re-raise it,
        # which allows Celery's retry mechanism to take over.
        logger.critical(f"A critical error occurred in process_and_store_content for URL {source_url}: {exc}", exc_info=True)
        raise exc




# ==============================================================================
# 2. SCHEDULED KNOWLEDGE UPDATE TASK
# ==============================================================================
# This is the single main task that will be triggered by Celery Beat every 2 hours.
# Its only job is to orchestrate the fetching and scraping by dispatching
# other, more specific tasks. This keeps the logic clean and modular.
# ==============================================================================
@shared_task(name="forex_agent.tasks.scheduled_knowledge_update")
def scheduled_knowledge_update():
    """
    The main scheduled task, triggered by Celery Beat. It orchestrates the
    fetching of news and the scraping of educational content.
    """
    logger.info("--- Starting Bi-Hourly Knowledge Update Cycle ---")
    
    # Dispatch the news fetching and scraping tasks to run in parallel in the background.
    fetch_and_process_market_news.delay()
    scrape_and_process_educational_content.delay()
    
    logger.info("--- Dispatched all knowledge update tasks. Cycle complete. ---")


# ==============================================================================
# 3. CONCRETE FETCHER AND SCRAPER TASKS
# ==============================================================================
# These are the worker tasks that do the actual fetching and scraping.
# They are designed to be self-contained and focused on a single source.
# ==============================================================================
@shared_task
def fetch_and_process_market_news():
    """
    Fetches market news concurrently from Finnhub and Alpha Vantage,
    then dispatches processing tasks for each article.
    """
    logger.info("Starting sub-task: fetch_and_process_market_news")

    async def fetch_news_concurrently():
        finnhub_key = config('FINNHUB_API_KEY', default=None)
        alpha_vantage_key = config('ALPHA_VANTAGE_API_KEY', default=None)

        async with httpx.AsyncClient(timeout=30) as client:
            tasks = []
            if finnhub_key:
                tasks.append(client.get(f"https://finnhub.io/api/v1/news?category=forex&token={finnhub_key}"))
            else:
                logger.warning("FINNHUB_API_KEY is not configured. Skipping Finnhub fetch.")

            if alpha_vantage_key:
                tasks.append(client.get(f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=financial_markets&apikey={alpha_vantage_key}"))
            else:
                logger.warning("ALPHA_VANTAGE_API_KEY is not configured. Skipping Alpha Vantage fetch.")

            if not tasks:
                logger.error("No news API keys configured. Cannot fetch news / Terminating news fetch task.")
                return
            
            # `return_exceptions=True` is crucial for resilience.
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # --- Process Finnhub Response ---
            try:
                if len(responses) > 0 and isinstance(responses[0], httpx.Response):
                    if responses[0].status_code == 200:
                        for item in responses[0].json()[:10]:
                            if all(k in item for k in ['url', 'headline', 'summary']):
                                process_and_store_content.delay(
                                    source_url=item['url'], title=item['headline'], raw_content=item['summary'],
                                    content_type='news', published_at_str=item.get('datetime')
                                )
                    else:
                        logger.error(f"Finnhub API returned status {responses[0].status_code}")
            except Exception as e:
                logger.error(f"Error processing Finnhub response: {e}")

            # --- Process Alpha Vantage Response ---
            try:
                if len(responses) > 1 and isinstance(responses[1], httpx.Response):
                    if responses[1].status_code == 200:
                        for item in responses[1].json().get('feed', [])[:10]:
                            if all(k in item for k in ['url', 'title', 'summary']):
                                process_and_store_content.delay(
                                    source_url=item['url'], title=item['title'], raw_content=item['summary'],
                                    content_type='news', published_at_str=item.get('time_published')
                                )
                    else:
                        logger.error(f"Alpha Vantage API returned status {responses[1].status_code}")
            except Exception as e:
                logger.error(f"Error processing Alpha Vantage response: {e}")


    try:
        asyncio.run(fetch_news_concurrently())
    except Exception as e:
        logger.critical(f"Critical error in fetch_and_process_market_news: {e}", exc_info=True)


@shared_task
def scrape_and_process_educational_content():
    """
    Scrapes educational content from BabyPips and dispatches processing tasks.
    """
    URL = "https://www.babypips.com/learn/forex"
    BASE_URL = "https://www.babypips.com"
    logger.info(f"Starting sub-task: scrape_and_process_educational_content from {URL}")

    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            response = client.get(URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # This selector must be precise and is fragile to website changes.
            lesson_links = {BASE_URL + a['href'] for a in soup.select('a[href^="/learn/forex/"]') if a.get('href')}
            logger.info(f"Found {len(lesson_links)} unique potential lesson URLs.")

            for i, url in enumerate(list(lesson_links)):
                if i >= 5: # Limit to 5 new articles per run to be respectful to the site
                    break
                
                try:
                    # Check if URL is already in the database before fetching
                    if ProcessedContent.objects.filter(source_url=url).exists():
                        continue
                    
                    lesson_response = client.get(url)
                    lesson_soup = BeautifulSoup(lesson_response.text, 'html.parser')
                    
                    title = lesson_soup.find('h1').get_text(strip=True) if lesson_soup.find('h1') else "Untitled"
                    content_div = lesson_soup.find('article') # A more generic selector that targets the main content area of a BabyPips lesson.
                    
                    if content_div:
                        raw_content = content_div.get_text(strip=True, separator='\n')
                        process_and_store_content.delay(
                            source_url=url, title=title, raw_content=raw_content, content_type='article'
                        )
                except Exception as e:
                    logger.error(f"Error processing individual lesson page {url}: {e}", exc_info=False)
    
    except Exception as e:
        logger.critical(f"A critical error occurred during the main scraping process: {e}", exc_info=True)