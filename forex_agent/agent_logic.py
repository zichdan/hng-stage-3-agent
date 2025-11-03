# forex_agent/agent_logic.py
import logging
from openai import OpenAI
from decouple import config
from pgvector.django import L2Distance

from .models import KnowledgeArticle, ConversationHistory
from .ai_services import embedding_generator

logger = logging.getLogger('forex_agent')

class ForexCompassAgent:
    """
    Encapsulates the core "thinking" logic of the Forex Compass agent.
    It handles retrieval-augmented generation (RAG), conversation history,
    and interaction with the final LLM.
    """
    SYSTEM_PROMPT = """
    You are 'Forex Compass', a friendly, patient, and highly knowledgeable AI mentor for beginner forex traders.
    Your primary goal is to provide safe, educational, and encouraging advice.

    RULES:
    1.  **Use Provided Context:** Base your answers on the "CONTEXT FROM KNOWLEDGE BASE" provided below. This is your primary source of truth.
    2.  **NEVER Give Financial Advice:** You must NEVER give trading signals, predict market movements, or suggest specific trades (e.g., "buy EUR/USD now"). This is your most important rule.
    3.  **Decline Politely:** If a user asks for financial advice, a prediction, or something you cannot do, you MUST politely decline and state that your purpose is purely educational.
    4.  **Be a Mentor:** Keep your tone simple, encouraging, and clear. Explain complex topics in a way a complete beginner can understand.
    5.  **Use History:** Refer to the "CONVERSATION HISTORY" to understand the flow of the conversation and provide relevant follow-up answers.
    """

    def __init__(self, context_id: str):
        self.context_id = context_id
        self.client = OpenAI(api_key=config("OPENAI_API_KEY", default=None))

    def get_response(self, user_prompt: str) -> str | None:
        """
        The main method to generate a response. It orchestrates the RAG process.
        """
        if not self.client.api_key:
            logger.critical("OPENAI_API_KEY is not configured. The agent cannot respond.")
            return "I'm sorry, my core AI service is not configured. I cannot process your request."

        try:
            # --- Step 1: Retrieval (The "R" in RAG) ---
            retrieved_context = self._perform_vector_search(user_prompt)

            # --- Step 2: Augmentation (The "A" in RAG) ---
            conversation_history = self._get_conversation_history()

            # --- Step 3: Generation (The "G" in RAG) ---
            # Construct the final, detailed prompt for the LLM.
            final_prompt = f"""
            {self.SYSTEM_PROMPT}

            ---
            CONTEXT FROM KNOWLEDGE BASE:
            {retrieved_context}
            ---
            CONVERSATION HISTORY:
            {conversation_history}
            ---
            CURRENT USER QUESTION:
            {user_prompt}
            """

            logger.debug(f"Generating LLM completion for context_id '{self.context_id}'...")
            response = self.client.chat.completions.create(
                model="gpt-4o", # A powerful and fast model for this task
                messages=[
                    {"role": "user", "content": final_prompt}
                ],
                temperature=0.3, # Lower temperature for more factual, less creative answers
                max_tokens=500
            )
            
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"An error occurred in the agent's get_response method: {e}", exc_info=True)
            return None # Return None to indicate failure

    def _perform_vector_search(self, query: str) -> str:
        """
        Performs a semantic vector search on our database to find the most
        relevant articles for the user's query.
        """
        try:
            # 1. Create an embedding for the user's query.
            query_embedding = embedding_generator.create_embedding(query)
            if query_embedding is None:
                logger.warning("Could not generate embedding for query, vector search will be skipped.")
                return "No information found in the knowledge base."

            # 2. Perform the vector search using cosine distance (L2Distance in pgvector).
            # We find the 3 most similar articles.
            articles = KnowledgeArticle.objects.order_by(
                L2Distance('embedding', query_embedding)
            )[:3]

            if not articles:
                return "No specific information was found in the knowledge base for this topic."

            # 3. Format the context for the LLM.
            context = "Here is some relevant information I found:\n\n"
            for article in articles:
                context += f"## {article.title}\n{article.processed_content}\n\n"
            return context

        except Exception as e:
            logger.error(f"Error during vector search: {e}", exc_info=True)
            return "An error occurred while searching the knowledge base."

    def _get_conversation_history(self) -> str:
        """
        Retrieves the last few turns of the conversation to provide context.
        """
        if not self.context_id:
            return "No previous conversation history."
            
        try:
            # Get the last 3 pairs of messages (6 total messages).
            history_records = ConversationHistory.objects.filter(context_id=self.context_id).order_by('-timestamp')[:6]
            
            if not history_records:
                return "This is the first message in the conversation."
            
            # Format the history for the LLM prompt.
            formatted_history = ""
            # We iterate in reverse to present it in chronological order.
            for record in reversed(history_records):
                formatted_history += f"User: {record.user_message}\n"
                formatted_history += f"You: {record.agent_message}\n"
            return formatted_history
        except Exception as e:
            logger.error(f"Error retrieving conversation history for context_id {self.context_id}: {e}", exc_info=True)
            return "An error occurred while retrieving conversation history."