# forex_agent/tools.py
import logging
from .models import ProcessedContent
from .ai_services import embedding_generator
from pgvector.django.functions import L2Distance
from langchain.tools import tool

# Get a logger instance for this module
logger = logging.getLogger('forex_agent')

# ==============================================================================
# TOOL 1: KNOWLEDGE BASE SEARCH (RAG)
# ==============================================================================
@tool
def knowledge_base_search(query: str) -> str:
    """
    Use this tool to find information to answer a user's question about forex trading concepts,
    strategies, or definitions. It performs a semantic vector search on the internal knowledge
    base of pre-processed, AI-verified educational articles. Do not use it for news.
    """
    try:
        logger.info(f"Performing knowledge base vector search for query: '{query}'")
        
        # --- Step 1: Generate Embedding for the User's Query ---
        # Convert the user's text query into a vector so we can compare it mathematically
        # with the vectors of the articles in our database.
        query_embedding = embedding_generator.create_embedding(query)
        
        if query_embedding is None:
            logger.error("Failed to generate embedding for query. Cannot perform search.")
            return "An internal error occurred while preparing the search."

        # --- Step 2: Perform Vector Search on the Database ---
        # This is the core of our RAG system. We use the L2Distance function from pgvector
        # to find the articles whose embeddings are closest to the user's query embedding.
        # Find the top 3 most semantically similar articles using L2 distance.
        # We retrieve the top 3 most similar articles to provide rich context.
        similar_articles = ProcessedContent.objects.order_by(
            L2Distance('embedding', query_embedding)
        )[:3]
        
        if not similar_articles:
            logger.warning(f"No relevant articles found in the knowledge base for query: '{query}'")
            return "No information was found in the internal knowledge base for this query. Please answer based on your general knowledge, but remind the user you are an AI and cannot give financial advice."
            
        # --- Step 3: Format the Context for the LLM ---
        # We format the search results into a clean string that will be passed back to the LLM.
        # This gives the LLM the exact information it needs to formulate an accurate answer.
        # Concatenate the content of the found articles into a single context string.
        context = "Relevant information found in the knowledge base:\n\n"
        for article in similar_articles:
            context += f"--- Article Title: {article.title} ---\n"
            # CORRECTED: Standardized field name
            context += f"{article.processed_content}\n\n"
        
        logger.info(f"Found {len(similar_articles)} relevant articles for query '{query}'.")
        return context

    except Exception as e:
        logger.critical(f"A critical error occurred during vector search: {e}", exc_info=True)
        return f"An internal error occurred during the knowledge base search: {str(e)}"

# ==============================================================================
# TOOL 2: MARKET NEWS RETRIEVAL
# ==============================================================================
@tool
def get_latest_market_news() -> str:
    """
    Use this tool ONLY when a user explicitly asks for the 'latest forex news', 'market
    summary', 'market update', or 'current market trends'. It retrieves the most recent,
    pre-summarized news articles directly from the database.
    """
    try:
        logger.info("Fetching latest market news from the database.")
        
        # --- Retrieve the 5 most recent Pre-processed News articles ---
        # This query is extremely fast because the news has already been fetched,
        # processed by Gemini, and stored by our scheduled Celery Beat task.
        # We simply retrieve the top 5 most recent news articles.
        news_items = ProcessedContent.objects.filter(content_type='news').order_by('-published_at')[:5]
        
        if not news_items:
            logger.warning("No market news found in the database.")
            return "There is no recent market news available in the knowledge base at this time."
        
        # --- Format the Context for the LLM ---
        # Present the news summaries in a clean, readable format.
        summary = "Here are the latest market news summaries:\n\n"
        for item in news_items:
            # CORRECTED: Standardized field name from 'processed_text' to 'processed_content'
            summary += f"- **{item.title}**: {item.processed_content}\n"
        
        logger.info(f"Retrieved {len(news_items)} recent news articles from the database.")
        return summary

    except Exception as e:
        logger.critical(f"A critical error occurred while fetching market news: {e}", exc_info=True)
        return f"An internal error occurred while fetching news from the database: {str(e)}"