# forex_agent/agent.py
import logging
from decouple import config
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from asgiref.sync import sync_to_async
from django.core.cache import cache

from .models import ConversationHistory, ProcessedContent # Make sure ProcessedContent is imported
from .tools import knowledge_base_search, get_latest_market_news
from .ai_services import ai_processor # Import the AI processor for the fallback

# Get a logger instance for this module, as configured in settings.py
logger = logging.getLogger('forex_agent')

# ==============================================================================
# AGENT DEFINITION
# ==============================================================================
# This is the core logic that defines the agent's persona, its capabilities (tools),
# and how it processes user requests. We use LangChain to orchestrate this.
# ==============================================================================

# --- The Agent's "Constitution" or System Prompt ---
# REVISED: This prompt now explicitly handles the "CONTEXT_NOT_FOUND" signal,
# enabling the general-purpose AI fallback you requested.
PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are 'Forex Compass', a friendly, patient, and highly knowledgeable AI mentor for beginner forex traders.

    Your primary goal is to provide safe, educational, and motivational advice. You must adhere to the following rules at all times:

    1.  **Use Your Tools First:** You have two tools: `knowledge_base_search` (for forex concepts) and `get_latest_market_news` (for news). You must ALWAYS try to use these tools first to answer questions about forex or market news.
    2.  **NEVER Give Financial Advice:** This is your most important rule. You must NEVER predict market movements, suggest specific trades (e.g., "should I buy EUR/USD?"), or give any form of financial advice.
    3.  **Safety First:** If a user's question is close to financial advice, you MUST politely decline and explicitly state: 'Disclaimer: I am an AI assistant and cannot provide financial advice. My purpose is purely educational. Please consult a qualified financial professional for investment advice.'
    4.  **How to Answer (Your Hybrid Logic):**
        * **If a tool finds information (RAG success):** Base your final answer *primarily* on the information provided by the tool. Your job is to rephrase this context into a simple, encouraging, and clear answer.
        * **If a tool returns 'CONTEXT_NOT_FOUND' (RAG fail):** This is your signal that the internal knowledge base has no answer. You MUST NOT mention the context was not found. Instead, you MUST output *only* the exact phrase: `FALLBACK_TO_GENERAL_KNOWLEDGE`.
    5.  **Small Talk:** For simple greetings or non-forex questions (like "hello", "how are you", "what is 2+2"), you MUST also output *only* the exact phrase: `FALLBACK_TO_GENERAL_KNOWLEDGE`.
    6.  **Use History:** Refer to the conversation history to understand the flow and provide relevant follow-up answers."""),
    
    # `MessagesPlaceholder` allows us to inject the conversation history.
    MessagesPlaceholder(variable_name="chat_history"),
    # The user's current input.
    ("human", "{input}"),
    # `agent_scratchpad` is where the agent does its "thinking" about which tool to call.
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

def create_forex_agent_executor(context_id: str):
    """
    Creates and configures the LangChain agent executor for a given conversation.
    This function is called by the agent logic for each new user request.
    """
    # ==============================================================================
    # THE FIX: DEFERRED IMPORT
    # Move the heavy import inside the function. This prevents it from running
    # during Django's startup, avoiding the import conflict.
    # ==============================================================================
    from langchain.agents import AgentExecutor, create_openai_tools_agent

    try:
        # --- Initialize the LLM ---
        # This LLM is your "General AI" fallback.
        llm = ChatOpenAI(
            model="gpt-4o", # A powerful and fast model for this task
            temperature=0.3, # Lower temperature for more factual, less creative answers
            openai_api_key=config("OPENAI_API_KEY")
        )

        # --- Define the Tools ---
        # These are the functions the agent is allowed to call.
        tools = [knowledge_base_search, get_latest_market_news]
        
        # --- Create the Agent ---
        # `create_openai_tools_agent` binds the LLM, tools, and NEW PROMPT together.
        agent = create_openai_tools_agent(llm, tools, PROMPT)
        
        # --- Create the Agent Executor ---
        # The executor is the runtime that actually calls the agent, executes the tools,
        # and returns the final response. `verbose=True` is invaluable for debugging.
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

        # --- Load Chat History ---
        # Retrieve the last 5 interactions (10 messages) for this session to provide short-term memory.
        history_records = ConversationHistory.objects.filter(context_id=context_id).order_by('-timestamp')[:5]
        chat_history = []
        for record in reversed(history_records): # Reverse to get chronological order
            chat_history.append(HumanMessage(content=record.user_message))
            chat_history.append(AIMessage(content=record.agent_message))
        
        logger.info(f"Created agent executor for context_id '{context_id}' with {len(chat_history) // 2} previous interactions.")
        return agent_executor, chat_history

    except Exception as e:
        logger.critical(f"Failed to create agent executor for context_id '{context_id}': {e}", exc_info=True)
        return None, []

# ==============================================================================
# ASYNCHRONOUS AGENT EXECUTION LOGIC (MERGED)
# ==============================================================================
# This function now orchestrates the full logic: RAG-first, with a direct AI fallback.
# It is called directly by the API view (views.py).

async def get_agent_response_async(user_prompt: str, context_id: str) -> str:
    """
    Handles a single user query asynchronously from start to finish, with a fallback
    to a general knowledge AI if the internal knowledge base has no answer.
    """
    final_agent_response = ""
    try:
        # --- Step 1: Check Redis Cache (Asynchronously) ---
        # We use sync_to_async to safely call synchronous cache functions.
        cache_key = f"forex_agent:response:{user_prompt}"
        cached_response = await sync_to_async(cache.get)(cache_key)
        
        if cached_response:
            logger.info(f"Cache hit for prompt: '{user_prompt}'. Returning cached response.")
            final_agent_response = cached_response
            # Save history even on a cache hit (fire-and-forget).
            await sync_to_async(ConversationHistory.objects.create)(
                context_id=context_id, user_message=user_prompt, agent_message=final_agent_response
            )
            return final_agent_response

        logger.info("Cache miss. Proceeding with live agent execution.")
        
        # --- Step 2: Create and Run the RAG-based LangChain Agent ---
        agent_executor, chat_history = await sync_to_async(create_forex_agent_executor)(context_id)
        if not agent_executor:
            raise Exception("Agent executor could not be created.")
            
        # Run the LangChain agent asynchronously
        result = await sync_to_async(agent_executor.invoke)({
            "input": user_prompt,
            "chat_history": chat_history
        })
        agent_response_text = result['output']

        # --- Step 3: Implement the Fallback Mechanism ---
        # Check if the agent's response is our specific trigger phrase.
        if "FALLBACK_TO_GENERAL_KNOWLEDGE" in agent_response_text:
            logger.warning(f"RAG agent triggered fallback for prompt: '{user_prompt}'. Calling general AI.")
            # Call the new, fast, async Q&A method from ai_services
            # We pass the original chat_history for context
            fallback_response = await ai_processor.get_general_qna_response(user_prompt, chat_history)
            final_agent_response = fallback_response
        else:
            # RAG was successful. The agent's response is the final answer.
            final_agent_response = agent_response_text
        
        # --- Step 4: Save and Cache the Final Response ---
        await sync_to_async(ConversationHistory.objects.create)(
            context_id=context_id,
            user_message=user_prompt,
            agent_message=final_agent_response
        )
        await sync_to_async(cache.set)(cache_key, final_agent_response, timeout=600)
        logger.info(f"Successfully generated and cached new response for context_id '{context_id}'.")

        return final_agent_response

    except Exception as e:
        logger.critical(f"An error occurred during async agent execution for context_id '{context_id}': {e}", exc_info=True)
        # Ensure a user-friendly error is always returned on failure
        if not final_agent_response:
             final_agent_response = "I'm sorry, I encountered an internal error while trying to process your request. Please try again in a moment."
        return final_agent_response