# forex_agent/ai_services.py
import logging
from decouple import config
import google.generativeai as genai
from openai import OpenAI, RateLimitError, APIError, APITimeoutError

# ==============================================================================
# INITIALIZATION & CONFIGURATION
# ==============================================================================

# Get a logger instance specific to the 'forex_agent' app.
# This logger is configured in `core/settings.py` to provide detailed output.
logger = logging.getLogger('forex_agent')

# --- Securely Configure API Clients ---
# This block initializes the AI clients in a fault-tolerant way. If API keys
# are missing from the .env file, the application will still start without
# crashing, but will log clear warnings that the AI services are disabled.
try:
    # Use python-decouple to safely load API keys from the .env file.
    gemini_api_key = config("GEMINI_API_KEY", default=None)
    openai_api_key = config("OPENAI_API_KEY", default=None)

    # Configure the Google Gemini client if the key is present.
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        logger.info("Google Gemini client configured successfully.")
    else:
        logger.warning("GEMINI_API_KEY not found in .env file. Gemini services will be unavailable.")

    # Configure the OpenAI client if the key is present.
    if openai_api_key:
        openai_client = OpenAI(api_key=openai_api_key, timeout=30.0)
        logger.info("OpenAI client configured successfully.")
    else:
        openai_client = None
        logger.warning("OPENAI_API_KEY not found in .env file. OpenAI services will be unavailable.")

except Exception as e:
    # Catch-all for any unexpected configuration errors.
    logger.critical(f"Fatal error during AI client configuration: {e}", exc_info=True)
    genai = None
    openai_client = None


# ==============================================================================
# SERVICE CLASS: GeminiContentProcessor
# ==============================================================================
# This class encapsulates all logic related to content processing using Gemini.
# It's responsible for cleaning, summarizing, and reformatting raw text.
# ==============================================================================

class GeminiContentProcessor:
    """
    A service class to handle content processing tasks (cleaning, summarizing)
    using the Google Gemini API.
    """
    def __init__(self, model_name='gemini-1.5-flash-latest'):
        """
        Initializes the processor. If the Gemini client failed to configure,
        the model attribute will be None, and all methods will fail gracefully.
        """
        if genai and gemini_api_key:
            self.model = genai.GenerativeModel(model_name)
        else:
            self.model = None
            logger.error("GeminiContentProcessor initialized without a valid model. All processing will fail.")

    def clean_and_format_text(self, raw_text: str, content_type: str = "financial article") -> str:
        """
        Sends raw text to Gemini with a robust prompt to clean, reformat, and
        tailor it for a beginner forex trader.

        Args:
            raw_text (str): The unstructured text from a web scrape or news API.
            content_type (str): A description of the content (e.g., "news article", "educational guide").

        Returns:
            str: The AI-processed, clean, and formatted content in Markdown,
                 or the original text if processing fails.
        """
        if not self.model:
            logger.error("GeminiContentProcessor cannot run because the model is not initialized.")
            return raw_text # Fallback to the original text if Gemini is not available


        # Truncate raw_text to a safe limit to avoid overly large and costly API requests.
        truncated_text = raw_text[:8000]

        # This is a highly engineered prompt designed to give the AI a clear role,
        # a specific audience, and a precise set of instructions.
        prompt = f"""
        As an expert financial content editor specializing in forex, your task is to take the following raw text and transform it.
        Your audience is a complete beginner in forex trading.

        Follow these instructions precisely:
        1.  **Analyze and Extract:** Read the text to understand its core message and key takeaways.
        2.  **Clean:** Aggressively remove all irrelevant information, such as advertisements, navigation links, promotional calls-to-action, and boilerplate text.
        3.  **Rewrite for a Beginner:** Rephrase the essential information in simple, clear, and concise language. Avoid jargon, or explain it immediately in simple terms if it's essential.
        4.  **Format:** Use Markdown to structure the content. Employ headings (#, ##), bullet points (* or -), and bold text (**) to make it highly readable and skimmable.

        The original content is a '{content_type}'. Your output should be a professionally formatted, easy-to-digest piece.

        RAW TEXT:
        ---
        {truncated_text}
        ---

        Cleaned and Formatted Content for a Beginner:
        """
        try:
            logger.debug(f"Sending text of type '{content_type}' to Gemini for processing.")
            response = self.model.generate_content(prompt)
            
            # Gemini includes safety ratings. It's crucial to check if the response
            # was blocked for safety reasons.
            if not response.parts:
                logger.warning(f"Gemini response for content type '{content_type}' was blocked or empty. Finish Reason: {response.prompt_feedback.block_reason}")
                return "Content could not be processed due to safety restrictions."
                 
            logger.debug("Successfully received processed content from Gemini.")
            return response.text
            
        except Exception as e:
            # This is a catch-all for any unexpected API errors (e.g., network issues, server errors).
            logger.error(f"An unexpected error occurred while calling the Gemini API: {e}", exc_info=True)
            return raw_text # Fallback to the original text in case of an API error

# ==============================================================================
# SERVICE CLASS: EmbeddingGenerator  (Using OpenAI)
# ==============================================================================
# This class handles the creation of vector embeddings, which are the
# mathematical representations of text used for semantic search.
# ==============================================================================

class EmbeddingGenerator:
    """
    A service class to generate vector embeddings for text using OpenAI's API.
    These embeddings are crucial for the semantic search (RAG) functionality.
    """
    def create_embedding(self, text: str) -> list[float] | None:
        """
        Creates a vector embedding for the given text using a specified model.
        Includes robust error handling for common API issues.

        Args:
            text (str): The text to be converted into an embedding.

        Returns:
            list[float] | None: A list of floats representing the vector, or None if an error occurs.
        """
        if not openai_client:
            logger.error("EmbeddingGenerator cannot run because the OpenAI client is not initialized.")
            return None

        try:
            # It's good practice to replace newlines to avoid potential issues with some embedding models.
            text_to_embed = text.replace("\n", " ")
            
            logger.debug(f"Requesting embedding for text snippet (length: {len(text_to_embed)})...")
            response = openai_client.embeddings.create(
                input=[text_to_embed],
                model="text-embedding-3-small" # Produces 1536 dimensions; great balance of cost and performance.
            )
            logger.debug("Successfully received embedding from OpenAI.")
            return response.data[0].embedding
            
        except RateLimitError as e:
            # This specific error occurs when you send requests too quickly.
            logger.error(f"OpenAI API rate limit exceeded. Please check your plan and usage. Error: {e}")
            return None
        except APITimeoutError as e:
            # This occurs if the API takes too long to respond.
            logger.error(f"OpenAI API request timed out. Error: {e}")
            return None
        except APIError as e:
            # This handles other generic API errors (e.g., server-side issues at OpenAI).
            logger.error(f"OpenAI API returned an error. Status: {e.status_code}. Message: {e.message}")
            return None
        except Exception as e:
            # A final catch-all for any other unexpected issues.
            logger.error(f"An unexpected error occurred while creating embedding: {e}", exc_info=True)
            return None

# ==============================================================================
# GLOBAL INSTANCES
# ==============================================================================
# Create single, reusable instances of our service classes. These can be
# imported and used throughout the `forex_agent` app, promoting a clean,
# service-oriented architecture.
# ==============================================================================
ai_processor = GeminiContentProcessor()
embedding_generator = EmbeddingGenerator()