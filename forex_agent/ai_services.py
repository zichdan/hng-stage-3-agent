# forex_agent/ai_services.py

import logging
from decouple import config
import google.generativeai as genai
from openai import OpenAI, RateLimitError, APIError, APITimeoutError
from asgiref.sync import sync_to_async # <-- IMPORT THIS

# ... (all other initializations remain the same) ...
# ==============================================================================
# INITIALIZATION & CONFIGURATION
# ==============================================================================
logger = logging.getLogger('forex_agent')
try:
    gemini_api_key = config("GEMINI_API_KEY", default=None)
    openai_api_key = config("OPENAI_API_KEY", default=None)
    openrouter_api_key = config("OPENROUTER_API_KEY", default=None)
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        logger.info("Google Gemini client configured successfully.")
    else:
        logger.warning("GEMINI_API_KEY not found in .env file. Gemini services will be unavailable.")
    if openai_api_key:
        openai_client = OpenAI(api_key=openai_api_key, timeout=30.0)
        logger.info("OpenAI client configured successfully.")
    else:
        openai_client = None
        logger.warning("OPENAI_API_KEY not found in .env file. OpenAI services will be unavailable.")
    if openrouter_api_key:
        openrouter_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_api_key,
            timeout=30.0
        )
        logger.info("OpenRouter client configured successfully for embeddings.")
    else:
        openrouter_client = None
        logger.warning("OPENROUTER_API_KEY not found in .env file. Embedding services will be unavailable.")
except Exception as e:
    logger.critical(f"Fatal error during AI client configuration: {e}", exc_info=True)
    genai = None
    openai_client = None
    openrouter_client = None


class GeminiContentProcessor:
    def __init__(self, model_name='models/gemini-1.5-flash-latest'):
        if genai and gemini_api_key:
            self.model = genai.GenerativeModel(model_name)
        else:
            self.model = None
            logger.error("GeminiContentProcessor initialized without a valid model. All processing will fail.")

    # ... (clean_and_format_text remains untouched) ...
    def clean_and_format_text(self, raw_text: str, content_type: str = "financial article") -> str:
        if not self.model:
            logger.error("GeminiContentProcessor cannot run because the model is not initialized.")
            return raw_text
        truncated_text = raw_text[:8000]
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
            if not response.parts:
                logger.warning(f"Gemini response for content type '{content_type}' was blocked or empty. Finish Reason: {response.prompt_feedback.block_reason}")
                return "Content could not be processed due to safety restrictions."
            logger.debug("Successfully received processed content from Gemini.")
            return response.text
        except Exception as e:
            logger.error(f"An unexpected error occurred while calling the Gemini API: {e}", exc_info=True)
            return raw_text

    # --- RAG REFINEMENT METHOD - REBUILT FOR STABILITY ---
    async def refine_context_with_llm(self, user_prompt: str, context: str, conversation_history: str) -> str:
        """
        RAG SUCCESS METHOD: Synthesizes context into a conversational answer using
        a thread-safe, synchronous API call to prevent event loop crashes.
        """
        if not self.model:
            logger.error("Cannot refine context because Gemini model is not initialized.")
            return "I'm sorry, but my connection to my knowledge source is currently unavailable."
        
        try:
            logger.info("Executing RAG Synthesis in a thread-safe manner.")
            prompt = f"""
            You are 'Forex Compass', a friendly and highly intelligent AI mentor for beginner forex traders.
            Your internal knowledge base has provided you with one or more relevant articles to answer the user's question.

            Your mission is to perform the following steps:
            1.  **Analyze and Synthesize:** Carefully read all the provided articles in the 'CONTEXT FROM KNOWLEDGE BASE' section. Find the common themes, key definitions, and essential information related to the user's question.
            2.  **Formulate a Comprehensive Answer:** Create a single, clear, and easy-to-understand answer. Do NOT just copy-paste from the articles. Your value is in synthesizing the information into a better, more complete explanation.
            3.  **Adhere to Rules:**
                *   Your entire answer MUST be based ONLY on the information within the provided context.
                *   Your tone should be encouraging, clear, and helpful.
                *   ABSOLUTELY NO FINANCIAL ADVICE.

            CONTEXT FROM KNOWLEDGE BASE:
            ---
            {context}
            ---
            CONVERSATION HISTORY:
            {conversation_history}
            ---
            CURRENT USER QUESTION:
            {user_prompt}

            Synthesized Answer for a Beginner:
            """
            
            # THE DEFINITIVE FIX:
            # We use the synchronous `generate_content` method and wrap it in `sync_to_async`.
            # This offloads the blocking, problematic library call to a worker thread,
            # completely isolating it from the main event loop and preventing the crash.
            response = await sync_to_async(self.model.generate_content)(prompt)
            
            return response.text

        except Exception as e:
            # This will now correctly catch errors from the synchronous call.
            logger.error(f"An unexpected error occurred during synchronous Gemini context refinement: {e}", exc_info=True)
            return "I found some information, but I apologize, I encountered an error while trying to formulate the answer."

    # --- FALLBACK METHOD - REBUILT FOR STABILITY ---
    async def get_general_qna_response(self, user_prompt: str, conversation_history: str) -> str:
        """
        FALLBACK METHOD: Uses a thread-safe, synchronous API call.
        """
        if not self.model:
            logger.error("Cannot get general response because Gemini model is not initialized.")
            return "I'm sorry, but my connection to my knowledge source is currently unavailable."
        
        try:
            logger.info("Executing fallback in a thread-safe manner.")
            prompt = f"""
            You are 'Forex Compass', a friendly and helpful AI mentor for beginner forex traders.
            A user is asking a question that is NOT in your specialized knowledge base.
            Your task is to answer their question from your general knowledge.

            IMPORTANT RULES:
            1.  **NEVER Give Financial Advice.**
            2.  **Safety First:** If the question is close to financial advice, you MUST politely decline.
            3.  **Be Helpful:** For all other questions, be friendly and answer directly.

            CONVERSATION HISTORY:
            {conversation_history}
            ---
            CURRENT USER QUESTION:
            {user_prompt}
            """
            # Apply the same stable pattern here for consistency.
            response = await sync_to_async(self.model.generate_content)(prompt)
            return response.text
        except Exception as e:
            logger.error(f"An unexpected error occurred during the synchronous Gemini fallback call: {e}", exc_info=True)
            return "I apologize, but I encountered an error while trying to answer your question from my general knowledge."

# ... (EmbeddingGenerator and global instances remain the same) ...
class EmbeddingGenerator:
    def create_embedding(self, text: str) -> list[float] | None:
        if not openrouter_client:
            logger.error("EmbeddingGenerator cannot run because the OpenRouter client is not initialized.")
            return None
        try:
            text_to_embed = text.replace("\n", " ")
            logger.debug(f"Requesting embedding from OpenRouter for text snippet (length: {len(text_to_embed)})...")
            response = openrouter_client.embeddings.create(
                input=[text_to_embed],
                model="openai/text-embedding-ada-002"
            )
            logger.debug("Successfully received embedding from OpenRouter.")
            return response.data[0].embedding
        except RateLimitError as e:
            logger.error(f"OpenRouter API rate limit exceeded. Error: {e}")
            return None
        except APITimeoutError as e:
            logger.error(f"OpenRouter API request timed out. Error: {e}")
            return None
        except APIError as e:
            logger.error(f"OpenRouter API returned an error. Status: {e.status_code}. Message: {e.message}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while creating OpenRouter embedding: {e}", exc_info=True)
            return None

ai_processor = GeminiContentProcessor()
embedding_generator = EmbeddingGenerator()

























































# # forex_agent/ai_services.py
# import logging
# from decouple import config
# import google.generativeai as genai
# from openai import OpenAI, RateLimitError, APIError, APITimeoutError
# # ==============================================================================
# # INITIALIZATION & CONFIGURATION
# # ==============================================================================

# # Get a logger instance specific to the 'forex_agent' app.
# # This logger is configured in `core/settings.py` to provide detailed output.
# logger = logging.getLogger('forex_agent')

# # --- Securely Configure API Clients ---
# # This block initializes the AI clients in a fault-tolerant way. If API keys
# # are missing from the .env file, the application will still start without
# # crashing, but will log clear warnings that the AI services are disabled.
# try:
#     # Use python-decouple to safely load API keys from the .env file.
#     gemini_api_key = config("GEMINI_API_KEY", default=None)
#     openai_api_key = config("OPENAI_API_KEY", default=None)
#     # NEW: Add the OpenRouter API Key
#     openrouter_api_key = config("OPENROUTER_API_KEY", default=None)
    
#     # Configure the Google Gemini client if the key is present.
#     if gemini_api_key:
#         genai.configure(api_key=gemini_api_key)
#         logger.info("Google Gemini client configured successfully.")
#     else:
#         logger.warning("GEMINI_API_KEY not found in .env file. Gemini services will be unavailable.")

#     # Configure the LangChain agent for OpenAI client if the key is present. (Still needed for the agent LLM)
#     if openai_api_key:
#         openai_client = OpenAI(api_key=openai_api_key, timeout=30.0)
#         logger.info("OpenAI client configured successfully.")
#     else:
#         openai_client = None
#         logger.warning("OPENAI_API_KEY not found in .env file. OpenAI services will be unavailable.")

#     # NEW: Create a separate client specifically for OpenRouter embeddings
#     if openrouter_api_key:
#         openrouter_client = OpenAI(
#             base_url="https://openrouter.ai/api/v1",
#             api_key=openrouter_api_key,
#             timeout=30.0
#         )
#         logger.info("OpenRouter client configured successfully for embeddings.")
#     else:
#         openrouter_client = None
#         logger.warning("OPENROUTER_API_KEY not found in .env file. Embedding services will be unavailable.")

# except Exception as e:
#     # Catch-all for any unexpected configuration errors.
#     logger.critical(f"Fatal error during AI client configuration: {e}", exc_info=True)
#     genai = None
#     openai_client = None
#     openrouter_client = None


# # ==============================================================================
# # SERVICE CLASS: GeminiContentProcessor
# # ==============================================================================
# # This class encapsulates all logic related to content processing using Gemini.
# # It's responsible for cleaning, summarizing, and reformatting raw text.
# # ==============================================================================

# class GeminiContentProcessor:
#     """
#     A service class to handle content processing tasks (cleaning, summarizing)
#     and general Q&A using the Google Gemini API.
#     """
#     def __init__(self, model_name='models/gemini-2.0-flash-001'): # CORRECTED: Using a confirmed available model
#         """
#         Initializes the processor. If the Gemini client failed to configure,
#         the model attribute will be None, and all methods will fail gracefully.
#         """
#         if genai and gemini_api_key:
#             self.model = genai.GenerativeModel(model_name)
#         else:
#             self.model = None
#             logger.error("GeminiContentProcessor initialized without a valid model. All processing will fail.")

#     def clean_and_format_text(self, raw_text: str, content_type: str = "financial article") -> str:
#         """
#         Sends raw text to Gemini with a robust prompt to clean, reformat, and
#         tailor it for a beginner forex trader.
#         (This method is retained for use by tasks.py)
#         """
#         if not self.model:
#             logger.error("GeminiContentProcessor cannot run because the model is not initialized.")
#             return raw_text # Fallback to the original text if Gemini is not available


#         # Truncate raw_text to a safe limit to avoid overly large and costly API requests.
#         truncated_text = raw_text[:8000]

#         # This is a highly engineered prompt designed to give the AI a clear role,
#         # a specific audience, and a precise set of instructions.
#         prompt = f"""
#         As an expert financial content editor specializing in forex, your task is to take the following raw text and transform it.
#         Your audience is a complete beginner in forex trading.

#         Follow these instructions precisely:
#         1.  **Analyze and Extract:** Read the text to understand its core message and key takeaways.
#         2.  **Clean:** Aggressively remove all irrelevant information, such as advertisements, navigation links, promotional calls-to-action, and boilerplate text.
#         3.  **Rewrite for a Beginner:** Rephrase the essential information in simple, clear, and concise language. Avoid jargon, or explain it immediately in simple terms if it's essential.
#         4.  **Format:** Use Markdown to structure the content. Employ headings (#, ##), bullet points (* or -), and bold text (**) to make it highly readable and skimmable.

#         The original content is a '{content_type}'. Your output should be a professionally formatted, easy-to-digest piece.

#         RAW TEXT:
#         ---
#         {truncated_text}
#         ---

#         Cleaned and Formatted Content for a Beginner:
#         """
#         try:
#             logger.debug(f"Sending text of type '{content_type}' to Gemini for processing.")
#             response = self.model.generate_content(prompt)
            
#             # Gemini includes safety ratings. It's crucial to check if the response
#             # was blocked for safety reasons.
#             if not response.parts:
#                 logger.warning(f"Gemini response for content type '{content_type}' was blocked or empty. Finish Reason: {response.prompt_feedback.block_reason}")
#                 return "Content could not be processed due to safety restrictions."
                 
#             logger.debug("Successfully received processed content from Gemini.")
#             return response.text
            
#         except Exception as e:
#             # This is a catch-all for any unexpected API errors (e.g., network issues, server errors).
#             logger.error(f"An unexpected error occurred while calling the Gemini API: {e}", exc_info=True)
#             return raw_text # Fallback to the original text in case of an API error

#     async def get_general_qna_response(self, user_prompt: str, conversation_history: str) -> str:
#         """
#         FALLBACK METHOD: This is used when the RAG search finds no context.
#         It answers a question using Gemini's general knowledge.
#         """
#         if not self.model:
#             logger.error("Cannot get general response because Gemini model is not initialized.")
#             return "I'm sorry, but my connection to my knowledge source is currently unavailable."
        
#         try:
#             logger.info("Executing fallback: Direct async call to Gemini for general knowledge.")
#             # This prompt is designed for direct, conversational Q&A.
#             prompt = f"""
#             You are 'Forex Compass', a friendly and helpful AI mentor for beginner forex traders.
#             A user is asking a question that is NOT in your specialized knowledge base.
#             Your task is to answer their question from your general knowledge.

#             IMPORTANT RULES:
#             1.  **NEVER Give Financial Advice:** You must NEVER predict market movements, suggest trades, or give financial advice.
#             2.  **Safety First:** If the question is close to financial advice, you MUST politely decline and state: 'Disclaimer: I am an AI assistant and cannot provide financial advice. My purpose is purely educational.'
#             3.  **Be Helpful:** For all other questions (greetings, math, general knowledge), be friendly and answer directly.

#             CONVERSATION HISTORY:
#             {conversation_history}
#             ---
#             CURRENT USER QUESTION:
#             {user_prompt}
#             """
#             # Use the async version of the generate_content method for a fast response.
#             response = await self.model.generate_content_async(prompt)
#             return response.text
#         except Exception as e:
#             logger.error(f"An unexpected error occurred during the Gemini fallback call: {e}", exc_info=True)
#             return "I apologize, but I encountered an error while trying to answer your question from my general knowledge."

#     # --- UPGRADED METHOD FOR RAG REFINEMENT ---
#     async def refine_context_with_llm(self, user_prompt: str, context: str, conversation_history: str) -> str:
#         """
#         RAG SUCCESS METHOD: Intelligently synthesizes context from one or more documents
#         into a single, coherent, and conversational answer.
#         """
#         if not self.model:
#             logger.error("Cannot refine context because Gemini model is not initialized.")
#             return "I'm sorry, but my connection to my knowledge source is currently unavailable."
        
#         try:
#             logger.info("Executing RAG Synthesis: Calling Gemini to synthesize context.")
            
#             # This is the new, more robust prompt designed for synthesis.
#             prompt = f"""
#             You are 'Forex Compass', a friendly and highly intelligent AI mentor for beginner forex traders.
#             Your internal knowledge base has provided you with one or more relevant articles to answer the user's question.

#             Your mission is to perform the following steps:
#             1.  **Analyze and Synthesize:** Carefully read all the provided articles in the 'CONTEXT FROM KNOWLEDGE BASE' section. Find the common themes, key definitions, and essential information related to the user's question.
#             2.  **Formulate a Comprehensive Answer:** Create a single, clear, and easy-to-understand answer. Do NOT just copy-paste from the articles. Your value is in synthesizing the information into a better, more complete explanation. If the articles provide different perspectives, merge them intelligently.
#             3.  **Adhere to Rules:**
#                 *   Your entire answer MUST be based ONLY on the information within the provided context. Do not use any external knowledge.
#                 *   Your tone should be encouraging, clear, and helpful, like a real mentor.
#                 *   ABSOLUTELY NO FINANCIAL ADVICE. Never suggest what to trade or predict market movements.

#             CONTEXT FROM KNOWLEDGE BASE:
#             ---
#             {context}
#             ---
#             CONVERSATION HISTORY:
#             {conversation_history}
#             ---
#             CURRENT USER QUESTION:
#             {user_prompt}

#             Synthesized Answer for a Beginner:
#             """
#             response = await self.model.generate_content_async(prompt)
#             return response.text
#         except Exception as e:
#             logger.error(f"An unexpected error occurred during Gemini context refinement: {e}", exc_info=True)
#             return "I found some information, but I apologize, I encountered an error while trying to formulate the answer."


# # ==============================================================================
# # SERVICE CLASS: EmbeddingGenerator (Using OpenRouter)
# # ==============================================================================
# # This class uses the OpenRouter client to avoid quota issues with direct API providers.
# # ==============================================================================

# class EmbeddingGenerator:
#     """
#     A service class to generate vector embeddings for text using OpenRouter's API.
#     These embeddings are crucial for the semantic search (RAG) functionality.
#     """
#     def create_embedding(self, text: str) -> list[float] | None:
#         """
#         Creates a vector embedding for the given text using OpenRouter's 'sentence-transformers/all-minilm-l6-v2"' model.
#         Includes robust error handling for common API issues.

#         Args:
#             text (str): The text to be converted into an embedding.

#         Returns:
#             list[float] | None: A list of floats representing the vector, or None if an error occurs.
#         """
#         if not openrouter_client:
#             logger.error("EmbeddingGenerator cannot run because the OpenRouter client is not initialized.")
#             return None

#         try:
#             # The `embeddings` function is the equivalent of OpenAI's `embeddings.create`.
#             # The model "openai/text-embedding-ada-002" is a standard, high-quality text embedding model.
#             text_to_embed = text.replace("\n", " ")
            
#             logger.debug(f"Requesting embedding from OpenRouter for text snippet (length: {len(text_to_embed)})...")
#             response = openrouter_client.embeddings.create(
#                 input=[text_to_embed],
#                 # CORRECTED: Use the official OpenAI model ID as hosted by OpenRouter.
#                 # This model produces 1536 dimensions.
#                 model="openai/text-embedding-ada-002"
#             )
#             logger.debug("Successfully received embedding from OpenRouter.")
#             return response.data[0].embedding
            
#         except RateLimitError as e:
#             logger.error(f"OpenRouter API rate limit exceeded. Error: {e}")
#             return None
#         except APITimeoutError as e:
#             logger.error(f"OpenRouter API request timed out. Error: {e}")
#             return None
#         except APIError as e:
#             logger.error(f"OpenRouter API returned an error. Status: {e.status_code}. Message: {e.message}")
#             return None
#         except Exception as e:
#             # A final catch-all for any unexpected issues with the embedding API.
#             logger.error(f"An unexpected error occurred while creating OpenRouter embedding: {e}", exc_info=True)
#             return None

# # ==============================================================================
# # GLOBAL INSTANCES
# # ==============================================================================
# # Create single, reusable instances of our service classes. These can be
# # imported and used throughout the `forex_agent` app, promoting a clean,
# # service-oriented architecture.
# # ==============================================================================
# ai_processor = GeminiContentProcessor()
# embedding_generator = EmbeddingGenerator()























































# # forex_agent/ai_services.py
# import logging
# from decouple import config
# import google.generativeai as genai
# from openai import OpenAI
# # ==============================================================================
# # INITIALIZATION & CONFIGURATION
# # ==============================================================================

# # Get a logger instance specific to the 'forex_agent' app.
# # This logger is configured in `core/settings.py` to provide detailed output.
# logger = logging.getLogger('forex_agent')

# # --- Securely Configure API Clients ---
# # This block initializes the AI clients in a fault-tolerant way. If API keys
# # are missing from the .env file, the application will still start without
# # crashing, but will log clear warnings that the AI services are disabled.
# try:
#     # Use python-decouple to safely load API keys from the .env file.
#     gemini_api_key = config("GEMINI_API_KEY", default=None)
#     openai_api_key = config("OPENAI_API_KEY", default=None)

#     # Configure the Google Gemini client if the key is present.
#     if gemini_api_key:
#         genai.configure(api_key=gemini_api_key)
#         logger.info("Google Gemini client configured successfully.")
#     else:
#         logger.warning("GEMINI_API_KEY not found in .env file. Gemini services will be unavailable.")

#     # Configure the OpenAI client if the key is present.
#     if openai_api_key:
#         openai_client = OpenAI(api_key=openai_api_key, timeout=30.0)
#         logger.info("OpenAI client configured successfully.")
#     else:
#         openai_client = None
#         logger.warning("OPENAI_API_KEY not found in .env file. OpenAI services will be unavailable.")

# except Exception as e:
#     # Catch-all for any unexpected configuration errors.
#     logger.critical(f"Fatal error during AI client configuration: {e}", exc_info=True)
#     genai = None
#     openai_client = None


# # ==============================================================================
# # SERVICE CLASS: GeminiContentProcessor
# # ==============================================================================
# # This class encapsulates all logic related to content processing using Gemini.
# # It's responsible for cleaning, summarizing, and reformatting raw text.
# # ==============================================================================

# class GeminiContentProcessor:
#     """
#     A service class to handle content processing tasks (cleaning, summarizing)
#     using the Google Gemini API.
#     """
#     def __init__(self, model_name='models/gemini-2.0-flash-001'): # CORRECTED: Using a confirmed available model
#         """
#         Initializes the processor. If the Gemini client failed to configure,
#         the model attribute will be None, and all methods will fail gracefully.
#         """
#         if genai and gemini_api_key:
#             self.model = genai.GenerativeModel(model_name)
#         else:
#             self.model = None
#             logger.error("GeminiContentProcessor initialized without a valid model. All processing will fail.")

#     def clean_and_format_text(self, raw_text: str, content_type: str = "financial article") -> str:
#         """
#         Sends raw text to Gemini with a robust prompt to clean, reformat, and
#         tailor it for a beginner forex trader.

#         Args:
#             raw_text (str): The unstructured text from a web scrape or news API.
#             content_type (str): A description of the content (e.g., "news article", "educational guide").

#         Returns:
#             str: The AI-processed, clean, and formatted content in Markdown,
#                  or the original text if processing fails.
#         """
#         if not self.model:
#             logger.error("GeminiContentProcessor cannot run because the model is not initialized.")
#             return raw_text # Fallback to the original text if Gemini is not available


#         # Truncate raw_text to a safe limit to avoid overly large and costly API requests.
#         truncated_text = raw_text[:8000]

#         # This is a highly engineered prompt designed to give the AI a clear role,
#         # a specific audience, and a precise set of instructions.
#         prompt = f"""
#         As an expert financial content editor specializing in forex, your task is to take the following raw text and transform it.
#         Your audience is a complete beginner in forex trading.

#         Follow these instructions precisely:
#         1.  **Analyze and Extract:** Read the text to understand its core message and key takeaways.
#         2.  **Clean:** Aggressively remove all irrelevant information, such as advertisements, navigation links, promotional calls-to-action, and boilerplate text.
#         3.  **Rewrite for a Beginner:** Rephrase the essential information in simple, clear, and concise language. Avoid jargon, or explain it immediately in simple terms if it's essential.
#         4.  **Format:** Use Markdown to structure the content. Employ headings (#, ##), bullet points (* or -), and bold text (**) to make it highly readable and skimmable.

#         The original content is a '{content_type}'. Your output should be a professionally formatted, easy-to-digest piece.

#         RAW TEXT:
#         ---
#         {truncated_text}
#         ---

#         Cleaned and Formatted Content for a Beginner:
#         """
#         try:
#             logger.debug(f"Sending text of type '{content_type}' to Gemini for processing.")
#             response = self.model.generate_content(prompt)
            
#             # Gemini includes safety ratings. It's crucial to check if the response
#             # was blocked for safety reasons.
#             if not response.parts:
#                 logger.warning(f"Gemini response for content type '{content_type}' was blocked or empty. Finish Reason: {response.prompt_feedback.block_reason}")
#                 return "Content could not be processed due to safety restrictions."
                 
#             logger.debug("Successfully received processed content from Gemini.")
#             return response.text
            
#         except Exception as e:
#             # This is a catch-all for any unexpected API errors (e.g., network issues, server errors).
#             logger.error(f"An unexpected error occurred while calling the Gemini API: {e}", exc_info=True)
#             return raw_text # Fallback to the original text in case of an API error

# # ==============================================================================
# # REFACTORED SERVICE CLASS: EmbeddingGenerator (Using Google AI)
# # ==============================================================================
# # This class now uses the Google Generative AI SDK for creating embeddings,
# # removing the dependency on OpenAI for this step and solving the quota issue.
# # ==============================================================================

# class EmbeddingGenerator:
#     """
#     A service class to generate vector embeddings for text using Google's AI Platform.
#     These embeddings are crucial for the semantic search (RAG) functionality.
#     """
#     def create_embedding(self, text: str) -> list[float] | None:
#         """
#         Creates a vector embedding for the given text using Google's 'embedding-001' model.
#         Includes robust error handling for common API issues.

#         Args:
#             text (str): The text to be converted into an embedding.

#         Returns:
#             list[float] | None: A list of floats representing the vector, or None if an error occurs.
#         """
#         if not genai or not gemini_api_key:
#             logger.error("EmbeddingGenerator cannot run because the Google Gemini client is not initialized.")
#             return None

#         try:
#             # The `embed_content` function is the equivalent of OpenAI's `embeddings.create`.
#             # The model 'models/embedding-001' is a standard, high-quality text embedding model.
#             logger.debug(f"Requesting Google AI embedding for text snippet (length: {len(text)})...")
#             result = genai.embed_content(
#                 model="models/embedding-001",
#                 content=text,
#                 task_type="RETRIEVAL_DOCUMENT", # Specifies the intended use case for better results
#                 title="Forex Article" # Optional title for context
#             )
#             logger.debug("Successfully received embedding from Google AI.")
#             return result['embedding']
            
#         except Exception as e:
#             # A final catch-all for any unexpected issues with the embedding API.
#             logger.error(f"An unexpected error occurred while creating a Google AI embedding: {e}", exc_info=True)
#             return None

# # ==============================================================================
# # GLOBAL INSTANCES
# # ==============================================================================
# # Create single, reusable instances of our service classes. These can be
# # imported and used throughout the `forex_agent` app, promoting a clean,
# # service-oriented architecture.
# # ==============================================================================
# ai_processor = GeminiContentProcessor()
# embedding_generator = EmbeddingGenerator()