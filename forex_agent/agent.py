# forex_agent/agent.py

import logging
from asgiref.sync import sync_to_async
from django.core.cache import cache
from langchain_core.messages import AIMessage, HumanMessage

from .models import ConversationHistory
# REVISED: Import the new NATIVELY ASYNC tools
from .tools import knowledge_base_search, get_latest_market_news
from .ai_services import ai_processor

# Get a logger instance for this module, as configured in settings.py
logger = logging.getLogger('forex_agent')

# ==============================================================================
# FULLY ASYNC AGENT LOGIC
# ==============================================================================
async def get_agent_response_async(user_prompt: str, context_id: str, chat_history_from_request: list) -> str:
    """
    Handles a user query within a fully asynchronous pipeline, from tool execution
    to LLM refinement, providing maximum stability.
    """
    try:
        # --- Step 1: Check Redis Cache (Asynchronously) ---
        cache_key = f"forex_agent:response:{user_prompt}"
        # The cache get operation is synchronous and needs wrapping.
        cached_response = await sync_to_async(cache.get)(cache_key)
        
        if cached_response:
            logger.info(f"Cache hit for prompt: '{user_prompt}'. Returning cached response.")
            await sync_to_async(ConversationHistory.objects.create)(
                context_id=context_id, user_message=user_prompt, agent_message=cached_response
            )
            return cached_response

        logger.info("Cache miss. Proceeding with custom agent execution.")
        
        # --- Step 2: Explicit and Asynchronous Tool Routing ---
        prompt_lower = user_prompt.lower()
        context = ""
        if any(keyword in prompt_lower for keyword in ['news', 'market update', 'latest', 'trends', 'market summary']):
            logger.info(f"Routing user query '{user_prompt}' to async news tool.")
            # SIMPLIFIED: Directly await the native async tool
            context = await get_latest_market_news()
        else:
            logger.info(f"Routing user query '{user_prompt}' to async knowledge base search.")
            # SIMPLIFIED: Directly await the native async tool
            context = await knowledge_base_search(user_prompt)

        # --- Step 3: Load and Format History ---
        chat_history = []
        if chat_history_from_request:
            for msg in chat_history_from_request:
                text = msg.get('text', '').replace('<p>', '').replace('</p>', '')
                if len(chat_history) % 2 == 0:
                    chat_history.append(HumanMessage(content=text))
                else:
                    chat_history.append(AIMessage(content=text))

        history_str = "\n".join([f"{'User' if isinstance(m, HumanMessage) else 'You'}: {m.content}" for m in chat_history])

        # --- Step 4: Hybrid Logic - RAG or Fallback ---
        agent_response_text = ""
        if "CONTEXT_NOT_FOUND" in context:
            logger.warning("RAG context not found. Triggering direct AI fallback.")
            agent_response_text = await ai_processor.get_general_qna_response(user_prompt, history_str)
        else:
            logger.info("RAG context found. Refining context with LLM.")
            agent_response_text = await ai_processor.refine_context_with_llm(user_prompt, context, history_str)
        
        # --- Step 5: Save and Cache the Final Response ---
        # Database and cache writes are synchronous and need wrapping.
        await sync_to_async(ConversationHistory.objects.create)(
            context_id=context_id,
            user_message=user_prompt,
            agent_message=agent_response_text
        )
        await sync_to_async(cache.set)(cache_key, agent_response_text, timeout=600)
        logger.info(f"Successfully generated and cached new response for context_id '{context_id}'.")

        return agent_response_text

    except Exception as e:
        logger.critical(f"An error occurred during async agent execution for context_id '{context_id}': {e}", exc_info=True)
        return "I'm sorry, I encountered an internal error while trying to process your request. Please try again in a moment."



















# # forex_agent/agent.py

# import logging
# from asgiref.sync import sync_to_async
# from django.core.cache import cache
# # REVISED: We only import the core message types, no agent framework.
# from langchain_core.messages import AIMessage, HumanMessage

# from .models import ConversationHistory
# # REVISED: We import the tools as regular Python functions.
# from .tools import knowledge_base_search, get_latest_market_news
# from .ai_services import ai_processor  # Import for the fallback and refinement mechanism

# # Get a logger instance for this module, as configured in settings.py
# logger = logging.getLogger('forex_agent')

# # ==============================================================================
# # REMOVED: AGENT DEFINITION
# # We no longer use the LangChain PROMPT, llm, or create_forex_agent_executor.
# # This entirely removes the source of the ModuleNotFoundError.
# # ==============================================================================


# # ==============================================================================
# # NEW ARCHITECTURE: EXPLICIT AGENT LOGIC
# # ==============================================================================
# # This function is now the complete "brain" of the agent. It replaces the
# # LangChain agent executor with a clear, explicit, and dependency-free logic flow.

# async def get_agent_response_async(user_prompt: str, context_id: str, chat_history_from_request: list) -> str:
#     """
#     Handles a single user query asynchronously with a RAG-first, fallback-second approach.
#     This new logic does not use the LangChain agent framework.
#     """
#     try:
#         # --- Step 1: Check Redis Cache (Asynchronously) ---
#         cache_key = f"forex_agent:response:{user_prompt}"
#         cached_response = await sync_to_async(cache.get)(cache_key)
        
#         if cached_response:
#             logger.info(f"Cache hit for prompt: '{user_prompt}'. Returning cached response.")
#             # Save history even on a cache hit (fire-and-forget).
#             await sync_to_async(ConversationHistory.objects.create)(
#                 context_id=context_id, user_message=user_prompt, agent_message=cached_response
#             )
#             return cached_response

#         logger.info("Cache miss. Proceeding with custom agent execution.")
        
#         # --- Step 2: Explicit Tool Routing ---
#         # A simple, reliable Python 'if' statement to decide which tool to use.
#         # This is faster and more predictable than an LLM call.
#         prompt_lower = user_prompt.lower()
#         context = ""
#         if any(keyword in prompt_lower for keyword in ['news', 'market update', 'latest', 'trends', 'market summary']):
#             logger.info(f"User query '{user_prompt}' contains news keywords. Routing to news tool.")
#             context = await sync_to_async(get_latest_market_news)()
#         else:
#             logger.info(f"Routing user query '{user_prompt}' to knowledge base search.")
#             context = await sync_to_async(knowledge_base_search)(user_prompt)

#         # --- Step 3: Load and Format History ---
#         # We still need history for context in both success and fallback scenarios.
#         chat_history = []
#         if chat_history_from_request:
#             for msg in chat_history_from_request:
#                 text = msg.get('text', '').replace('<p>', '').replace('</p>', '')
#                 # Assuming the history alternates user/agent
#                 if len(chat_history) % 2 == 0:
#                     chat_history.append(HumanMessage(content=text))
#                 else:
#                     chat_history.append(AIMessage(content=text))

#         history_str = "\n".join([f"{'User' if isinstance(m, HumanMessage) else 'You'}: {m.content}" for m in chat_history])

#         # --- Step 4: Hybrid Logic - RAG or Fallback ---
#         # This is the core of the new architecture. We check the 'signal' from our tools.
#         agent_response_text = ""
#         if "CONTEXT_NOT_FOUND" in context:
#             # RAG Fail: The tool found nothing. Trigger the general knowledge fallback.
#             logger.warning("RAG context not found. Triggering direct AI fallback.")
#             agent_response_text = await ai_processor.get_general_qna_response(user_prompt, history_str)
#         else:
#             # RAG Success: The tool found context. Trigger the new refinement method.
#             logger.info("RAG context found. Refining context with LLM.")
#             # We need to add `refine_context_with_llm` to ai_services.py
#             agent_response_text = await ai_processor.refine_context_with_llm(user_prompt, context, history_str)
        
#         # --- Step 5: Save and Cache the Final Response ---
#         await sync_to_async(ConversationHistory.objects.create)(
#             context_id=context_id,
#             user_message=user_prompt,
#             agent_message=agent_response_text
#         )
#         await sync_to_async(cache.set)(cache_key, agent_response_text, timeout=600)
#         logger.info(f"Successfully generated and cached new response for context_id '{context_id}'.")

#         return agent_response_text

#     except Exception as e:
#         logger.critical(f"An error occurred during async agent execution for context_id '{context_id}': {e}", exc_info=True)
#         # Ensure a user-friendly error is always returned on failure
#         return "I'm sorry, I encountered an internal error while trying to process your request. Please try again in a moment."