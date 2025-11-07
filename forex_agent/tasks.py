# forex_agent/tasks.py
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup
from celery import shared_task
from decouple import config
from django.conf import settings # Import Django's settings
from django.core.cache import cache
from django.db import transaction

# --- Local Imports ---
# Import the AI services and all necessary database models.
from .ai_services import ai_processor, embedding_generator
from .models import RawContent, ProcessedContent, ConversationHistory
from .agent import create_forex_agent_executor

# Get a logger instance for this module, as configured in settings.py.
# This allows us to see detailed, app-specific logs during execution.
logger = logging.getLogger('forex_agent')

# ==============================================================================
# SECTION 1: DECOUPLED AI PROCESSING PIPELINE
# ==============================================================================
# This new architecture uses a staging model (`RawContent`) to decouple
# fetching from AI processing. This is the definitive solution to prevent API
# rate limit errors and make the entire data pipeline more resilient.

def _execute_ai_processing(raw_content_item: RawContent):
    """
    This is the core processing logic, refactored into a standard Python function.
    It handles the AI-powered cleaning, embedding, and final storage of a single piece of content.
    By being a separate function, it's reusable and can be tested independently.
    """
    source_url = raw_content_item.source_url
    title = raw_content_item.title
    
    logger.info(f"Starting AI processing for staged content: {source_url}")

    # --- Step 1: Check for Duplicates in the final ProcessedContent table ---
    # This is a crucial final check to prevent re-processing if a task failed
    # after processing but before marking the raw item as complete.
    if ProcessedContent.objects.filter(source_url=source_url).exists():
        logger.warning(f"Content from URL {source_url} already exists in the final 'ProcessedContent' table. Skipping.")
        return

    # --- Step 2: AI-Powered Content Processing (using Gemini) ---
    logger.debug(f"Calling AI processor for '{title}'...")
    processed_text = ai_processor.clean_and_format_text(raw_content_item.raw_content, raw_content_item.content_type)
    if not processed_text or "could not be processed" in processed_text:
        # Raise an exception to signal that this item failed processing.
        raise ValueError(f"AI content processing failed or returned empty for '{title}'.")

    # --- Step 3: Vector Embedding Generation (using OpenAI) ---
    logger.debug(f"Generating embedding for '{title}'...")
    embedding_vector = embedding_generator.create_embedding(processed_text)
    if embedding_vector is None:
        # Raise an exception to signal failure.
        raise ValueError(f"Embedding generation failed for '{title}'.")

    # --- Step 4: Prepare Robust Datetime Timestamp Parsing ---
    published_at_dt = None
    published_at_str = raw_content_item.published_at_str
    if published_at_str:
        try:
            if isinstance(published_at_str, int) or published_at_str.isdigit():
                published_at_dt = datetime.fromtimestamp(int(published_at_str), tz=ZoneInfo("UTC"))
            else:
                published_at_dt = datetime.strptime(published_at_str, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo("UTC"))
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse timestamp '{published_at_str}' for URL {source_url}. Error: {e}")

    # --- Step 5: Save to Final Database Table ---
    logger.debug(f"Saving processed article '{title}' to database...")
    ProcessedContent.objects.create(
        source_url=source_url,
        title=title,
        processed_content=processed_text,
        embedding=embedding_vector,
        content_type=raw_content_item.content_type,
        published_at=published_at_dt,
    )
    logger.info(f"Successfully processed and stored content from: {source_url}")


@shared_task(name="forex_agent.tasks.process_one_staged_content_item")
def process_one_staged_content_item():
    """
    NEW: This scheduled task runs frequently (e.g., every 5 minutes). Its sole purpose is to
    safely process ONE item from the RawContent staging table. This ensures AI API calls
    are always spaced out, providing a robust solution to rate-limiting.
    """
    try:
        # Use a database transaction to ensure atomicity. `select_for_update` locks the
        # chosen row, preventing other workers from processing the same item simultaneously.
        with transaction.atomic():
            # Get the oldest unprocessed item that isn't already locked by another worker.
            item_to_process = RawContent.objects.select_for_update(skip_locked=True).filter(is_processed=False).order_by('created_at').first()
            
            if not item_to_process:
                logger.debug("No new raw content in the staging queue to process.")
                return

            logger.info(f"Found item in staging queue: '{item_to_process.title}'")
            
            # Execute the core AI processing and storage logic.
            _execute_ai_processing(item_to_process)

            # If the processing was successful (no exception was raised), mark the raw item as processed.
            item_to_process.is_processed = True
            item_to_process.save()

    except Exception as e:
        # If any step in `_execute_ai_processing` fails, an exception is raised.
        # The transaction is automatically rolled back, so the item is NOT marked as processed.
        # It will be automatically retried the next time this scheduled task runs.
        item_id = locals().get('item_to_process') and item_to_process.id
        logger.critical(f"A critical error occurred in the staging processor for item ID {item_id or 'N/A'}: {e}", exc_info=True)


# ==============================================================================
# SECTION 2: DATA FETCHING AND STAGING TASKS
# ==============================================================================
# These tasks are responsible ONLY for fetching raw data and saving it to the `RawContent`
# staging table. They do not call AI APIs directly.

@shared_task(name="forex_agent.tasks.fetch_and_process_market_news")
def fetch_and_process_market_news():
    """
    REFACTORED: Fetches market news and saves it to the RawContent staging table.
    This task is fully synchronous and does not involve any AI processing.
    """
    logger.info("--- Starting Scheduled Task: Fetch Market News ---")
    finnhub_key = config('FINNHUB_API_KEY', default=None)
    alpha_vantage_key = config('ALPHA_VANTAGE_API_KEY', default=None)

    with httpx.Client(timeout=30) as client:
        # --- Process Finnhub ---
        if finnhub_key:
            try:
                response = client.get(f"https://finnhub.io/api/v1/news?category=forex&token={finnhub_key}")
                response.raise_for_status()
                for item in response.json()[:10]:
                    if all(k in item for k in ['url', 'headline', 'summary']):
                        # Save to staging table. If URL exists, update it.
                        RawContent.objects.update_or_create(
                            source_url=item['url'],
                            defaults={
                                'title': item['headline'],
                                'raw_content': item['summary'],
                                'content_type': 'news',
                                'published_at_str': str(item.get('datetime')),
                                'is_processed': False
                            }
                        )
            except Exception as e:
                logger.error(f"Error processing Finnhub response: {e}", exc_info=True)

        # --- Process Alpha Vantage ---
        if alpha_vantage_key:
            try:
                response = client.get(f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=financial_markets&apikey={alpha_vantage_key}")
                response.raise_for_status()
                for item in response.json().get('feed', [])[:10]:
                    if all(k in item for k in ['url', 'title', 'summary']):
                        RawContent.objects.update_or_create(
                            source_url=item['url'],
                            defaults={
                                'title': item['title'],
                                'raw_content': item['summary'],
                                'content_type': 'news',
                                'published_at_str': item.get('time_published'),
                                'is_processed': False
                            }
                        )
            except Exception as e:
                logger.error(f"Error processing Alpha Vantage response: {e}", exc_info=True)


@shared_task(name="forex_agent.tasks.scrape_babypips_for_links")
def scrape_babypips_for_links():
    """
    Dispatcher Task: Scrapes the BabyPips main page to find new lesson URLs
    and dispatches worker tasks to scrape each page individually.
    """
    # Load config from settings.py instead of hardcoding
    config = settings.SCRAPER_CONFIG["BABYPIPS"]
    START_URL = config["START_URL"]
    BASE_URL = config["BASE_URL"]
    
    logger.info(f"--- Starting Scheduled Task: Scrape BabyPips for Links from {START_URL} ---")

    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            response = client.get(START_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all potential lesson links on the page
            lesson_links = soup.select(config["LINK_SELECTOR"])
            all_urls_on_page = {f"{BASE_URL}{link.get('href')}" for link in lesson_links if link.get('href')}

            if not all_urls_on_page:
                logger.warning(f"No lesson links found at {START_URL} using selector '{config['LINK_SELECTOR']}'. The website structure may have changed.")
                return

            # --- Efficiency Step: Check against both tables to avoid re-scraping ---
            existing_urls_raw = set(RawContent.objects.values_list('source_url', flat=True))
            existing_urls_processed = set(ProcessedContent.objects.values_list('source_url', flat=True))
            existing_urls = existing_urls_raw.union(existing_urls_processed)
            
            new_urls_to_process = all_urls_on_page - existing_urls
            
            if not new_urls_to_process:
                logger.info("No new lesson URLs found on BabyPips. All content is up to date.")
                return

            logger.info(f"Found {len(new_urls_to_process)} new lesson links. Dispatching scraping sub-tasks...")
            
            # Dispatch a sub-task for each new URL, respecting the limit.
            for url in list(new_urls_to_process)[:config["RESPECTFUL_LIMIT"]]:
                scrape_and_stage_page.delay(url)

    except Exception as e:
        logger.critical(f"A critical error occurred during the main link scraping task: {e}", exc_info=True)


@shared_task(
    rate_limit='15/m', # Respectful rate limit: max 15 pages per minute.
    autoretry_for=(httpx.RequestError, httpx.HTTPStatusError), # Automatically retry on network/server errors.
    retry_backoff=True, # Use exponential backoff (e.g., wait 1s, then 2s, 4s...).
    retry_kwargs={'max_retries': 3} # Retry up to 3 times before failing.
)
def scrape_and_stage_page(url: str):
    """
    Worker Sub-task: Scrapes a single page and saves its raw content to the RawContent staging table.
    """
    config = settings.SCRAPER_CONFIG["BABYPIPS"]
    try:
        logger.debug(f"Scraping and staging page: {url}")
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_element = soup.select_one(config["TITLE_SELECTOR"])
            content_element = soup.select_one(config["CONTENT_SELECTOR"])

            if title_element and content_element:
                title = title_element.get_text(strip=True)
                raw_content = content_element.get_text(strip=True, separator='\n')
                
                # Hand off the raw content to the staging table for later, controlled processing.
                RawContent.objects.create(
                    source_url=url,
                    title=title,
                    raw_content=raw_content,
                    content_type='article'
                )
            else:
                logger.warning(f"Could not extract title or content from {url}. Page structure might have changed.")

    except Exception as e:
        logger.error(f"Failed to scrape and stage page {url}: {e}", exc_info=True)


# ==============================================================================
# ON-DEMAND CELERY TASK: The Reactive Responder
# ==============================================================================
# This is the on-demand Celery task that gets triggered by a user's message
# from the a2a_protocol view. It orchestrates the entire process of getting an answer.
# Its logic remains exactly the same as your original, robust implementation.
# ==============================================================================

@shared_task(name="forex_agent.tasks.process_user_query")
def process_user_query(task_details: dict):
    """
    The main on-demand Celery task that handles a single user query from start to finish.
    """
    # --- Unpack Task Details ---
    # We pass a single dictionary to keep the task signature clean and extensible.
    user_prompt = task_details.get('user_prompt')
    context_id = task_details.get('context_id')
    # webhook_config = task_details.get('webhook_config')        # TO BE USED LATER 
    
    logger.info(f"Received user query for context_id '{context_id}': '{user_prompt}'")
     
    # TO BE USED LATER 
    # if not all([user_prompt, context_id, webhook_config]):
    #     logger.error(f"Task aborted: received with missing details: {task_details}")       # TO BE USED LATER 
    #     return

    
    try:
        # --- Step 1: Check Redis Cache ---
        # This is a critical performance and cost-saving optimization for repeated questions.
        cache_key = f"forex_agent:response:{user_prompt}"
        if (cached_response := cache.get(cache_key)):
            logger.info(f"Cache hit for prompt: '{user_prompt}'. Returning cached response.")
            # Even with a cache hit, we save the interaction to keep the history complete.
            ConversationHistory.objects.create(
                context_id=context_id, user_message=user_prompt, agent_message=cached_response
            )
            # Send the cached response back immediately
            send_response_to_webhook(cached_response, task_details)
            return

        logger.info("Cache miss. Proceeding with live agent execution.")
        
        # --- Step 2: Create and Run the Agent ---
        # We create a new agent executor for each request to load the latest chat history.
        agent_executor, chat_history = create_forex_agent_executor(context_id)
        if not agent_executor:
            raise Exception("Agent executor could not be created.")
            
        # Invoke the agent. This is where the magic happens: the agent will
        # decide whether to call a tool, get the tool's output, and then
        # generate the final human-readable response.
        result = agent_executor.invoke({
            "input": user_prompt,
            "chat_history": chat_history
        })
        agent_response_text = result['output']

        # --- Step 3: Save and Cache the New Response ---
        ConversationHistory.objects.create(
            context_id=context_id,
            user_message=user_prompt,
            agent_message=agent_response_text
        )
        # Cache the new response for 10 minutes to handle repeat questions quickly.
        cache.set(cache_key, agent_response_text, timeout=600) # Cache for 10 minutes
        logger.info(f"Successfully generated and cached new response for context_id '{context_id}'.")

        # --- Step 4: Send Response to Webhook ---
        send_response_to_webhook(agent_response_text, task_details)

    except Exception as e:
        logger.critical(f"An error occurred during agent execution for context_id '{context_id}': {e}", exc_info=True)
        error_message = "I'm sorry, I encountered an internal error while trying to process your request. Please try again in a moment."
        # Send a user-friendly error message back to the user
        send_response_to_webhook(error_message, task_details, state="failed")


def send_response_to_webhook(answer: str, task_details: dict, state: str = "completed"):
    """
    Helper function to format the final A2A TaskResult and POST it to the webhook URL.
    This is a synchronous function called at the end of the Celery task.
    """
    webhook_url = task_details.get('webhook_config', {}).get('url')
    if not webhook_url:
        logger.error("No webhook URL provided in task details. Cannot send response.")
        return

    # Construct the A2A-compliant JSON-RPC response payload.
    response_payload = {
        "jsonrpc": "2.0",
        "id": task_details.get('request_id'),
        "result": {
            "id": task_details.get('task_id'),
            "contextId": task_details.get('context_id'),
            "status": {
                "state": state,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "message": {
                    "kind": "message", "role": "agent",
                    "parts": [{"kind": "text", "text": answer}]
                }
            },
            "kind": "task"
        }
    }
    
    try:
        logger.debug(f"Sending final response to webhook: {webhook_url}")
        with httpx.Client() as client:
            response = client.post(webhook_url, json=response_payload, timeout=15)
            response.raise_for_status()
            logger.info(f"Successfully sent webhook response for task {task_details.get('task_id')}.")
    except httpx.RequestError as e:
        logger.error(f"Failed to send webhook response for task {task_details.get('task_id')}: {e}")



































