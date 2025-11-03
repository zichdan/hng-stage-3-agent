from django.test import TestCase

# Create your tests here.
import asyncio
import logging
from datetime import datetime
from celery import shared_task
import httpx
from bs4 import BeautifulSoup
from decouple import config

from .models import KnowledgeArticle
from .ai_services import ai_processor, embedding_generator

# Get a logger instance specific to this app, as configured in settings.py
logger = logging.getLogger('forex_agent')

# ==============================================================================
# HELPER TASK: The Core Processing Pipeline
# ==============================================================================

@shared_task(
    name="process_and_store_content_task",
    autoretry_for=(Exception,), # Automatically retry on any exception
    retry_kwargs={'max_retries': 3, 'countdown': 60} # Retry up to 3 times, with a 1-min delay
)
def process_and_store_content_task(source_url: str, title: str, raw_content: str, content_type: str, published_at_str: str = None):
    """
    A robust, retryable task that forms the core of our knowledge pipeline.
    It takes raw data, processes it with AI, generates an embedding, and saves it to the database.
    """
    try:
        # Step 1: Check if this content already exists in our database.
        # This prevents redundant processing and API calls.
        if KnowledgeArticle.objects.filter(source_url=source_url).exists():
            logger.info(f"Content from {source_url} already exists. Skipping processing.")
            return f"Skipped: {title}"

        logger.info(f"Processing new content: '{title}' from {source_url}")

        # Step 2: Use our Gemini AI service to clean and articulate the content.
        processed_text = ai_processor.clean_and_format_text(raw_content, content_type=content_type)
        if not processed_text or "Content could not be processed" in processed_text:
            logger.warning(f"AI processing failed or returned empty for '{title}'. Aborting storage.")
            return f"AI Processing Failed: {title}"

        # Step 3: Use our OpenAI service to generate a vector embedding for the clean text.
        embedding_vector = embedding_generator.create_embedding(processed_text)
        if embedding_vector is None:
            logger.error(f"Failed to generate embedding for '{title}'. Aborting storage.")
            # We raise an exception here to trigger Celery's retry mechanism.
            raise ValueError(f"Embedding generation failed for {title}")

        # Step 4: Parse the publication date string into a datetime object if it exists.
        published_at = None
        if published_at_str:
            try:
                # Attempt to parse common ISO 8601 formats.
                published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                logger.warning(f"Could not parse publication date '{published_at_str}' for '{title}'.")
        
        # Step 5: Save the fully processed article to our PostgreSQL database.
        KnowledgeArticle.objects.create(
            source_url=source_url,
            title=title,
            processed_content=processed_text,
            embedding=embedding_vector,
            content_type=content_type,
            published_at=published_at,
        )
        logger.info(f"Successfully processed and stored: '{title}'")
        return f"Successfully stored: {title}"

    except Exception as e:
        logger.critical(f"A critical error occurred in the processing pipeline for {source_url}: {e}", exc_info=True)
        # Re-raise the exception to let Celery handle the retry logic.
        raise

# ==============================================================================
# SCHEDULED TASK 1: Fetching Market News
# ==============================================================================

async def _fetch_news_from_source(client, name, url, headers=None):
    """Asynchronous helper to fetch news from a single source with robust error handling."""
    try:
        response = await client.get(url, headers=headers, timeout=20.0)
        response.raise_for_status()  # Raises an exception for 4xx or 5xx status codes
        logger.info(f"Successfully fetched news from {name}.")
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching from {name}: Status {e.response.status_code} for URL {e.request.url}")
    except httpx.RequestError as e:
        logger.error(f"Network-related error fetching from {name}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching from {name}: {e}", exc_info=True)
    return None

@shared_task(name="fetch_and_process_market_news")
def fetch_and_process_market_news():
    """
    Scheduled task to fetch news from Finnhub and Alpha Vantage concurrently.
    It then dispatches sub-tasks to process and store each news article.
    """
    logger.info("Starting scheduled task: Fetch and Process Market News.")
    
    finnhub_key = config('FINNHUB_API_KEY')
    alpha_vantage_key = config('ALPHA_VANTAGE_API_KEY')

    async def main():
        async with httpx.AsyncClient() as client:
            # Define the API calls to be made
            tasks = [
                _fetch_news_from_source(
                    client, "Finnhub",
                    f"https://finnhub.io/api/v1/news?category=forex&token={finnhub_key}"
                ),
                _fetch_news_from_source(
                    client, "Alpha Vantage",
                    f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=financial_markets&apikey={alpha_vantage_key}"
                )
            ]
            results = await asyncio.gather(*tasks)

            # --- Process Finnhub Results ---
            finnhub_news = results[0]
            if finnhub_news and isinstance(finnhub_news, list):
                logger.info(f"Processing {len(finnhub_news)} articles from Finnhub.")
                for article in finnhub_news[:10]: # Process the top 10 articles
                    if all(k in article for k in ['url', 'headline', 'summary']):
                        process_and_store_content_task.delay(
                            source_url=article['url'],
                            title=article['headline'],
                            raw_content=article['summary'],
                            content_type='news',
                            published_at_str=datetime.utcfromtimestamp(article['datetime']).isoformat() if 'datetime' in article else None
                        )

            # --- Process Alpha Vantage Results ---
            alpha_vantage_news = results[1]
            if alpha_vantage_news and 'feed' in alpha_vantage_news:
                logger.info(f"Processing {len(alpha_vantage_news['feed'])} articles from Alpha Vantage.")
                for article in alpha_vantage_news['feed'][:10]: # Process the top 10 articles
                    if all(k in article for k in ['url', 'title', 'summary']):
                         process_and_store_content_task.delay(
                            source_url=article['url'],
                            title=article['title'],
                            raw_content=article['summary'],
                            content_type='news',
                            published_at_str=datetime.strptime(article['time_published'], '%Y%m%dT%H%M%S').isoformat() if 'time_published' in article else None
                        )
    
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Critical error in the main news fetching process: {e}", exc_info=True)


# ==============================================================================
# SCHEDULED TASK 2: Scraping Educational Content
# ==============================================================================

@shared_task(name="scrape_and_process_educational_content")
def scrape_and_process_educational_content():
    """
    Scheduled task to scrape educational content from a source like BabyPips.
    This is a simplified example; a production system would have more complex logic.
    """
    logger.info("Starting scheduled task: Scrape and Process Educational Content.")
    
    # Target URL for scraping - the main "School of Pipsology" page
    BASE_URL = "https://www.babypips.com"
    START_URL = f"{BASE_URL}/learn/forex"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(START_URL)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all lesson links. This CSS selector targets the links within the course outline.
            # This needs to be kept up-to-date if the website structure changes.
            lesson_links = soup.select("a[href*='/learn/forex/']")

            if not lesson_links:
                logger.warning("No lesson links found on BabyPips. The page structure may have changed.")
                return

            logger.info(f"Found {len(lesson_links)} potential lesson links on BabyPips.")
            
            # Process a limited number of new articles each run to avoid overwhelming the system.
            processed_count = 0
            for link in lesson_links:
                if processed_count >= 5: # Limit to 5 new articles per run
                    break
                
                full_url = BASE_URL + link['href']
                
                # Check if we've already processed this URL
                if KnowledgeArticle.objects.filter(source_url=full_url).exists():
                    continue

                # Fetch and parse the individual lesson page
                logger.debug(f"Scraping new lesson: {full_url}")
                lesson_response = client.get(full_url)
                lesson_soup = BeautifulSoup(lesson_response.text, 'html.parser')

                # Extract title and content (selectors must be precise)
                title_element = lesson_soup.find('h1')
                content_element = lesson_soup.find('div', class_='content-body') # Example class

                if title_element and content_element:
                    title = title_element.get_text(strip=True)
                    raw_content = content_element.get_text(strip=True)
                    
                    # Dispatch the processing task
                    process_and_store_content_task.delay(
                        source_url=full_url,
                        title=title,
                        raw_content=raw_content,
                        content_type='article'
                    )
                    processed_count += 1
                else:
                    logger.warning(f"Could not find title or content for {full_url}.")

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error scraping BabyPips: Status {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Network error scraping BabyPips: {e}")
    except Exception as e:
        logger.critical(f"A critical error occurred during the BabyPips scraping process: {e}", exc_info=True)