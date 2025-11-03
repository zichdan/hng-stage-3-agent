# forex_agent/tasks.py
import asyncio
import logging
from datetime import datetime
from decouple import config
import httpx
from bs4 import BeautifulSoup
from celery import shared_task
from django.utils.dateparse import parse_datetime

# Import our AI services and database models
from .ai_services import ai_processor, embedding_generator
from .models import ProcessedContent

# ==============================================================================
# SETUP & CONFIGURATION
# ==============================================================================

# Get a logger instance specific to the 'forex_agent' app
logger = logging.getLogger('forex_agent')

# Load API keys securely from the .env file
FINNHUB_API_KEY = config('FINNHUB_API_KEY', default=None)
ALPHA_VANTAGE_API_KEY = config('ALPHA_VANTAGE_API_KEY', default=None)


# ==============================================================================
# HELPER SUB-TASK
# ==============================================================================

@shared_task(rate_limit='10/m', acks_late=True) # Rate limit to 10 tasks per minute to avoid overwhelming AI APIs
def process_and_store_content(source_url: str, title: str, raw_content: str, content_type: str, published_at_str: str = None):
    """
    A generic, robust sub-task to process a single piece of content.
    This task is called by the main fetching and scraping tasks. It handles:
    1. AI-powered content cleaning and formatting.
    2. Vector embedding generation.
    3. Saving the final, processed content to the database.
    """
    try:
        logger.info(f"Starting processing for content from: {source_url}")

        # Step 1: Check if this content already exists in our database.
        # --- Prevent Duplicate Processing ---
        # This check is crucial to avoid re-processing the same content, saving time and API costs.
        if ProcessedContent.objects.filter(source_url=source_url).exists():
            logger.info(f"Content from {source_url} already exists in the database. Skipping Processing.")
            return f"Skipped: {title}"


        # Step 2: Use our Gemini AI service to clean and articulate the content.
        # --- AI Content Articulation (using Gemini) ---
        # This is where we transform raw, messy data into high-quality knowledge.
        logger.debug(f"Sending raw content (length: {len(raw_content)}) to AI processor...")
        processed_text = ai_processor.clean_and_format_text(raw_content, content_type=content_type)
        if not processed_text or "Content could not be processed" in processed_text:
            logger.error(f"AI content processing failed for {source_url} or returned empty for '{title}'. Aborting storage.")
            return f"AI Processing Failed: {title}"


        # Step 3: Use our OpenAI service to generate a vector embedding for the clean text.
        # --- Vector Embedding Generation (using OpenAI) ---
        # This creates the vector needed for our semantic search (RAG) system.
        logger.debug("Generating vector embedding for processed content...")
        embedding_vector = embedding_generator.create_embedding(processed_text)
        if embedding_vector is None:
            logger.error(f"Failed to generate embedding for {source_url}. Aborting storage.")
            return


        # Step 4: Parse the publication date string into a datetime object if it exists.
        # --- Parse Datetime ---
        # Safely parse the publication date string into a timezone-aware datetime object.
        published_at = None
        if published_at_str:
            try:
                published_at = parse_datetime(published_at_str)
            except ValueError:
                logger.warning(f"Could not parse datetime string: {published_at_str}")



        # Step 5: Save the fully processed article to our PostgreSQL database.
        # --- Save to Database ---
        # The update_or_create method is an "upsert" operation. It safely creates the
        # new record or updates it if it somehow already exists.
        obj, created = ProcessedContent.objects.update_or_create(
            source_url=source_url,
            defaults={
                'title': title,
                'processed_text': processed_text,
                'embedding': embedding_vector,
                'content_type': content_type,
                'published_at': published_at,
            }
        )
        
        if created:
            logger.info(f"Successfully CREATED new knowledge article: {title}")
        else:
            logger.info(f"Successfully UPDATED existing knowledge article: {title}")

    except Exception as e:
        # A robust catch-all for any unexpected errors during the process.
        logger.critical(f"A critical error occurred in process_and_store_content for URL {source_url}: {e}", exc_info=True)


# ==============================================================================
# SCHEDULED MAIN TASKS (for Celery Beat)
# ==============================================================================

@shared_task(name="forex_agent.tasks.scheduled_knowledge_update")
def scheduled_knowledge_update():
    """
    This is the main scheduled task, triggered by Celery Beat every 2 hours.
    It orchestrates the fetching of news and the scraping of educational content
    by dispatching other asynchronous tasks.
    """
    logger.info("--- Starting Bi-Hourly Knowledge Update Cycle ---")
    
    # Dispatch the news fetching task to run in the background.
    fetch_market_news.delay()
    
    # Dispatch the web scraping task to run in the background.
    scrape_educational_content.delay()
    
    logger.info("--- Dispatched all knowledge update tasks. Cycle complete. ---")


@shared_task
def fetch_market_news():
    """
    Fetches news from Finnhub and Alpha Vantage concurrently, then dispatches
    sub-tasks to process each article.
    """
    logger.info("Starting market news fetch...")

    # --- Asynchronous Fetching Logic ---
    async def fetch_all():
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []
            
            # Task for Finnhub API
            if FINNHUB_API_KEY:
                finnhub_url = f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_API_KEY}"
                tasks.append(client.get(finnhub_url))
                logger.debug("Added Finnhub request to task list.")
            else:
                logger.warning("FINNHUB_API_KEY not set. Skipping Finnhub.")

            # Task for Alpha Vantage API
            if ALPHA_VANTAGE_API_KEY:
                alpha_vantage_url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=financial_markets&apikey={ALPHA_VANTAGE_API_KEY}"
                tasks.append(client.get(alpha_vantage_url))
                logger.debug("Added Alpha Vantage request to task list.")
            else:
                logger.warning("ALPHA_VANTAGE_API_KEY not set. Skipping Alpha Vantage.")

            if not tasks:
                logger.error("No news API keys are configured. Cannot fetch news.")
                return

            # Execute all requests concurrently
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            return responses

    # Run the async fetching function
    responses = asyncio.run(fetch_all())
    
    # --- Process Responses ---
    # Process Finnhub response (assuming it's the first one if it exists)
    try:
        finnhub_response = responses[0]
        if isinstance(finnhub_response, httpx.Response):
            finnhub_response.raise_for_status()
            news_articles = finnhub_response.json()
            logger.info(f"Fetched {len(news_articles)} articles from Finnhub.")
            for article in news_articles[:10]: # Process the top 10 articles
                if article.get('url') and article.get('headline') and article.get('summary'):
                    process_and_store_content.delay(
                        source_url=article['url'],
                        title=article['headline'],
                        raw_content=article['summary'],
                        content_type='news',
                        published_at_str=datetime.utcfromtimestamp(article['datetime']).isoformat() + "Z"  if 'datetime' in article else None
                    )
    except Exception as e:
        logger.error(f"Failed to process Finnhub response: {e}", exc_info=True)

    # Process Alpha Vantage response (assuming it's the second one if it exists)
    try:
        av_response = responses[1]
        if isinstance(av_response, httpx.Response):
            av_response.raise_for_status()
            feed = av_response.json().get('feed', [])
            logger.info(f"Fetched {len(feed)} articles from Alpha Vantage.")
            for article in feed[:10]: # Process the top 10 articles
                if article.get('url') and article.get('title') and article.get('summary'):
                    process_and_store_content.delay(
                        source_url=article['url'],
                        title=article['title'],
                        raw_content=article['summary'],
                        content_type='news',
                        published_at_str=article['time_published'] # Format: YYYYMMDDTHHMMSS
                    )
    except Exception as e:
        logger.error(f"Failed to process Alpha Vantage response: {e}", exc_info=True)


@shared_task
def scrape_educational_content():
    """
    Scrapes a target educational website (e.g., BabyPips), extracts content,
    and dispatches sub-tasks to process each article.
    """
    # NOTE: Web scraping must be done responsibly. Always check a site's robots.txt
    # and terms of service. This is a simplified example.
    scrape_url = "https://www.babypips.com/learn/forex"
    logger.info(f"Starting educational content scrape from {scrape_url}")

    try:
        response = httpx.get(scrape_url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # This CSS selector needs to be specific to the site's structure.
        # It finds all links within the main course outline.
        lesson_links = soup.select('div.course a[href]')
        logger.debug(f"Found {len(lesson_links)} potential lesson links on the main page.")

        for link in lesson_links[:5]: # Scrape the first 5 new lessons to be polite
            full_url = "https://www.babypips.com" + link['href']
            
            # Use another task to process each link individually
            process_single_scraped_page.delay(full_url)
            
    except Exception as e:
        logger.error(f"Failed to scrape main page {scrape_url}: {e}", exc_info=True)

@shared_task
def process_single_scraped_page(url: str):
    """A sub-task to handle the scraping and processing of a single URL."""
    try:
        logger.debug(f"Scraping individual lesson page: {url}")
        page_response = httpx.get(url, follow_redirects=True, timeout=30.0)
        page_response.raise_for_status()
        page_soup = BeautifulSoup(page_response.text, 'html.parser')
        
        # These selectors are specific to BabyPips and would need updating if the site changes.
        title = page_soup.find('h1').get_text(strip=True) if page_soup.find('h1') else "Untitled"
        content_div = page_soup.find('div', class_='fx-section') # Adjust class name as needed
        
        if title and content_div:
            raw_content = content_div.get_text(separator='\n', strip=True)
            process_and_store_content.delay(
                source_url=url,
                title=title,
                raw_content=raw_content,
                content_type='article'
            )
        else:
            logger.warning(f"Could not find title or content div on page: {url}")
            
    except Exception as e:
        logger.error(f"Failed to scrape or process individual page {url}: {e}", exc_info=True)