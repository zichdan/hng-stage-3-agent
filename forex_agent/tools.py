# forex_agent/tools.py

import logging
from asgiref.sync import sync_to_async
from .models import ProcessedContent
from .ai_services import embedding_generator
from pgvector.django.functions import L2Distance

# Get a logger instance for this module
logger = logging.getLogger('forex_agent')

# This constant remains our primary defense against oversized API requests.
MAX_CONTEXT_CHARACTERS = 8000

# ==============================================================================
# TOOL 1: KNOWLEDGE BASE SEARCH (RAG) - REBUILT AS ASYNC
# ==============================================================================
async def knowledge_base_search(query: str) -> str:
    """
    (NATIVELY ASYNC) Performs a semantic vector search and intelligently builds a
    context string, using async-safe database calls.
    """
    try:
        logger.info(f"Performing knowledge base vector search for query: '{query}'")
        
        # --- Step 1: Generate Embedding for the User's Query ---
        # Embedding generation is I/O bound (network call), so we run it in a thread.
        query_embedding = await sync_to_async(embedding_generator.create_embedding)(query)
        
        if query_embedding is None:
            logger.error("Failed to generate embedding for query. Cannot perform search.")
            return "CONTEXT_NOT_FOUND: An internal error occurred while preparing the search."

        # --- Step 2: Perform Vector Search on the Database (Async-Safe) ---
        # The .order_by() and slicing is synchronous, but the final evaluation
        # that hits the database needs to be wrapped for an async context.
        # We wrap the entire query execution in sync_to_async.
        similar_articles_query = ProcessedContent.objects.order_by(
            L2Distance('embedding', query_embedding)
        )[:3]
        
        similar_articles = await sync_to_async(list)(similar_articles_query)
        
        if not similar_articles:
            logger.warning(f"No relevant articles found in the knowledge base for query: '{query}'")
            return "CONTEXT_NOT_FOUND: No specific information was found for this query."
            
        # --- Step 3: Intelligently Build the Context (Crucial Defense) ---
        context_parts = []
        current_char_count = 0
        
        for article in similar_articles:
            header = f"--- Article Title: {article.title} ---\n"
            content = article.processed_content
            part_size = len(header) + len(content)
            
            if current_char_count + part_size > MAX_CONTEXT_CHARACTERS:
                remaining_space = MAX_CONTEXT_CHARACTERS - current_char_count - len(header) - 20 # for '... (truncated)'
                if remaining_space > 100:
                    truncated_content = content[:remaining_space] + "... (truncated)"
                    context_parts.append(f"{header}{truncated_content}")
                break
            
            context_parts.append(f"{header}{content}")
            current_char_count += part_size

        if not context_parts:
            logger.warning(f"No articles could be fit into the context window for query: '{query}'")
            return "CONTEXT_NOT_FOUND: Relevant information was found but was too large to process."

        final_context = "Relevant information found in the knowledge base:\n\n" + "\n\n".join(context_parts)
        
        logger.info(f"Successfully built context from {len(context_parts)} articles for query '{query}'.")
        return final_context

    except Exception as e:
        logger.critical(f"A critical error occurred during async vector search: {e}", exc_info=True)
        return f"CONTEXT_NOT_FOUND: An internal error occurred during the knowledge base search: {str(e)}"

# ==============================================================================
# TOOL 2: MARKET NEWS RETRIEVAL - REBUILT AS ASYNC
# ==============================================================================
async def get_latest_market_news() -> str:
    """
    (NATIVELY ASYNC) Retrieves the most recent news articles using async-safe
    database calls.
    """
    try:
        logger.info("Fetching latest market news from the database.")
        
        # Wrap the synchronous database call to make it safe in an async context.
        news_items_query = ProcessedContent.objects.filter(content_type='news').order_by('-published_at')[:5]
        news_items = await sync_to_async(list)(news_items_query)
        
        if not news_items:
            logger.warning("No market news found in the database.")
            return "CONTEXT_NOT_FOUND: There is no recent market news available in the knowledge base at this time."

        summary = "Here are the latest market news summaries:\n\n"
        for item in news_items:
            summary += f"- **{item.title}**: {item.processed_content}\n"
        
        logger.info(f"Retrieved {len(news_items)} recent news articles from the database.")
        return summary

    except Exception as e:
        logger.critical(f"A critical error occurred while fetching market news: {e}", exc_info=True)
        return f"CONTEXT_NOT_FOUND: An internal error occurred while fetching news from the database: {str(e)}"

































# # forex_agent/tools.py
# import logging
# from .models import ProcessedContent
# from .ai_services import embedding_generator
# from pgvector.django.functions import L2Distance

# # Get a logger instance for this module
# logger = logging.getLogger('forex_agent')

# # Define a safe maximum character limit for the context passed to the LLM.
# # This prevents API errors for oversized prompts and is the main fix for the crash.
# # 8000 characters is roughly 2000-2500 tokens, a very safe size for modern models.
# MAX_CONTEXT_CHARACTERS = 8000

# # ==============================================================================
# # TOOL 1: KNOWLEDGE BASE SEARCH (RAG) - UPGRADED
# # ==============================================================================
# def knowledge_base_search(query: str) -> str:
#     """
#     Performs a semantic vector search and intelligently builds a context string
#     from multiple sources, ensuring it doesn't exceed a safe size limit.
#     This is the core fix for the application's instability.
#     """
#     try:
#         logger.info(f"Performing knowledge base vector search for query: '{query}'")
        
#         # --- Step 1: Generate Embedding for the User's Query ---
#         # Convert the user's text query into a vector so we can compare it mathematically
#         # with the vectors of the articles in our database.
#         query_embedding = embedding_generator.create_embedding(query)
        
#         if query_embedding is None:
#             logger.error("Failed to generate embedding for query. Cannot perform search.")
#             # REVISED: This signal is crucial for the new agent logic in agent.py
#             return "CONTEXT_NOT_FOUND: An internal error occurred while preparing the search."

#         # --- Step 2: Perform Vector Search on the Database ---
#         # This is the core of our RAG system. We use the L2Distance function from pgvector
#         # to find the articles whose embeddings are closest to the user's query embedding.
#         # Find the top 3 most semantically similar articles using L2 distance.
#         # We retrieve the top 3 most similar articles to provide rich context.
#         similar_articles = ProcessedContent.objects.order_by(
#             L2Distance('embedding', query_embedding)
#         )[:3]
        
#         if not similar_articles:
#             logger.warning(f"No relevant articles found in the knowledge base for query: '{query}'")
#             # REVISED: Return a clear, machine-readable signal for the fallback mechanism.
#             return "CONTEXT_NOT_FOUND: No specific information was found in the internal knowledge base for this query."
            
#         # --- Step 3: Intelligently Build the Context for the LLM (THE CRITICAL FIX) ---
#         # Instead of blindly concatenating, we build the context piece-by-piece,
#         # respecting the character limit to prevent API failures.

#         # We format the search results into a clean string that will be passed back to the LLM.
#         # This gives the LLM the exact information it needs to formulate an accurate answer.
#         # Concatenate the content of the found articles into a single context string.

#         context_parts = []
#         current_char_count = 0

#         for article in similar_articles:
#             header = f"--- Article Title: {article.title} ---\n"
#             content = article.processed_content

#             # Estimate the size of this chunk
#             part_size = len(header) + len(content)

#             # If adding this full article exceeds the limit, we might need to truncate or skip.
#             if current_char_count + part_size > MAX_CONTEXT_CHARACTERS:
#                 # Calculate remaining space
#                 remaining_space = MAX_CONTEXT_CHARACTERS - current_char_count - len(header) - 20 # 20 for '... (truncated)'

#                 # Only add a truncated version if there's meaningful space left
#                 if remaining_space > 100: # Don't add just a tiny sliver of text
#                     truncated_content = content[:remaining_space] + "... (truncated)"
#                     context_parts.append(f"{header}{truncated_content}")

#                 # We've hit the limit, so we must stop adding more articles.
#                 break

#             # If it fits, add the full article content
#             context_parts.append(f"{header}{content}")
#             current_char_count += part_size

#         if not context_parts:
#             # This would only happen if the very first article is too massive, which is unlikely.
#             logger.warning(f"No articles could be fit into the context window for query: '{query}'")
#             return "CONTEXT_NOT_FOUND: Relevant information was found but was too large to process."

#         final_context = "Relevant information found in the knowledge base:\n\n" + "\n\n".join(context_parts)
        
#         logger.info(f"Successfully built context from {len(context_parts)} articles for query '{query}'.")
#         return final_context

#     except Exception as e:
#         logger.critical(f"A critical error occurred during vector search: {e}", exc_info=True)
#         # REVISED: Ensure we always return the signal on failure
#         return f"CONTEXT_NOT_FOUND: An internal error occurred during the knowledge base search: {str(e)}"

# # ==============================================================================
# # TOOL 2: MARKET NEWS RETRIEVAL
# # ==============================================================================
# def get_latest_market_news() -> str:
#     """
#     Retrieves the most recent, pre-summarized news articles from the database.
#     """
#     try:
#         logger.info("Fetching latest market news from the database.")
        
#         # This query is extremely fast because the news has already been processed.
#         news_items = ProcessedContent.objects.filter(content_type='news').order_by('-published_at')[:5]
        
#         if not news_items:
#             logger.warning("No market news found in the database.")
#             # REVISED: Return a clear, machine-readable signal.
#             return "CONTEXT_NOT_FOUND: There is no recent market news available in the knowledge base at this time."

#         # --- Format the Context for the LLM ---
#         # Present the news summaries in a clean, readable format.
#         summary = "Here are the latest market news summaries:\n\n"
#         for item in news_items:
#             # CORRECTED: Standardized field name from 'processed_text' to 'processed_content'
#             summary += f"- **{item.title}**: {item.processed_content}\n"
        
#         logger.info(f"Retrieved {len(news_items)} recent news articles from the database.")
#         return summary

#     except Exception as e:
#         logger.critical(f"A critical error occurred while fetching market news: {e}", exc_info=True)
#         # REVISED: Ensure we always return the signal on failure
#         return f"CONTEXT_NOT_FOUND: An internal error occurred while fetching news from the database: {str(e)}"