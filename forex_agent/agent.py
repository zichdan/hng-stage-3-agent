# forex_agent/agent.py
import httpx
import logging
from decouple import config

from celery import shared_task
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from django.core.cache import cache

from .models import ConversationHistory
from .tools import knowledge_base_search, get_latest_market_news

# Get a logger instance for this module
logger = logging.getLogger('forex_agent')

# ==============================================================================
# AGENT DEFINITION
# ==============================================================================
# This is the core logic that defines the agent's persona, its capabilities (tools),
# and how it processes user requests. We use LangChain to orchestrate this.
# ==============================================================================

# --- The Agent's "Constitution" or System Prompt ---
# This is the most important part of the agent's design. It sets the rules,
# defines the persona, and instructs the AI on how and when to use its tools.
PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are 'Forex Compass', a friendly, patient, and highly knowledgeable AI mentor for beginner forex traders.

    Your primary goal is to provide safe, educational, and motivational advice. You must adhere to the following rules at all times:

    1.  **Use Your Tools:** You have access to tools. You should ALWAYS prefer to use them to answer questions. Use `knowledge_base_search` for forex concepts and `get_latest_market_news` for news.
    2.  **NEVER Give Financial Advice:** You must NEVER give trading signals, predict market movements, suggest specific trades (e.g., "should I buy EUR/USD?"), or give any form of financial advice.
    3.  **Safety First:** If a user's question is close to asking for financial advice, you MUST politely decline and explicitly state: 'Disclaimer: I am an AI assistant and cannot provide financial advice. My purpose is purely educational. Please consult a qualified financial professional for investment advice.'
    4.  **Answer from Context:** When your tools provide information, base your final answer primarily on that information to ensure accuracy and safety.
    5.  **Be a Mentor:** Keep your tone simple, encouraging, and clear. Explain complex topics in a way a complete beginner can understand, If you don't have an answer, it's better to say so and offer to explain a related concept. Maintain an encouraging and supportive tone.
    """),
    # 6.  **Use History:** Refer to the "CONVERSATION HISTORY" to understand the flow of the conversation and provide relevant follow-up answers.
    
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
    """
    try:
        # --- Initialize the LLM ---
        # We use a powerful model like GPT-4o, which is excellent at tool usage.
        # Temperature is set low to make the agent more factual and less creative.
        llm = ChatOpenAI(
            model="gpt-4o", # A powerful and fast model for this task
            temperature=0.3, # Lower temperature for more factual, less creative answers
            openai_api_key=config("OPENAI_API_KEY")
        )

        # --- Define the Tools ---
        # These are the functions the agent is allowed to call.
        tools = [knowledge_base_search, get_latest_market_news]
        
        # --- Create the Agent ---
        # `create_openai_tools_agent` binds the LLM, tools, and prompt together.
        agent = create_openai_tools_agent(llm, tools, PROMPT)
        
        # --- Create the Agent Executor ---
        # The executor is the runtime that actually calls the agent, executes the tools,
        # and returns the final response. `verbose=True` is great for debugging.
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

        # --- Load Chat History ---
        # Retrieve the last 10 messages for this session to provide short-term memory.
        history_records = ConversationHistory.objects.filter(context_id=context_id).order_by('-timestamp')[:5]
        chat_history = []
        for record in reversed(history_records): # Reverse to get chronological order
            chat_history.append(HumanMessage(content=record.user_message))
            chat_history.append(AIMessage(content=record.agent_message))
        
        logger.info(f"Created agent executor for context_id '{context_id}' with {len(chat_history)} history messages.")
        return agent_executor, chat_history

    except Exception as e:
        logger.critical(f"Failed to create agent executor: {e}", exc_info=True)
        return None, []

# ==============================================================================
# ON-DEMAND CELERY TASK: The Reactive Responder
# ==============================================================================
# This is the on-demand Celery task that gets triggered by a user's message.
# It orchestrates the entire process of getting an answer.
# ==============================================================================

@shared_task(name="forex_agent.agent.process_user_query")
def process_user_query(task_details: dict):
    """
    The main on-demand Celery task that handles a single user query from start to finish.
    """
    # --- Unpack Task Details ---
    # We pass a dictionary to keep the task signature clean.
    user_prompt = task_details.get('user_prompt')
    context_id = task_details.get('context_id')
    # webhook_config = task_details.get('webhook_config')        # TO BE USED LATER 
    
    logger.info(f"Received user query for context_id '{context_id}': '{user_prompt}'")


    try:
        # --- Step 1: Check Redis Cache ---
        # This is a critical performance and cost-saving optimization.
        cache_key = f"forex_agent:response:{user_prompt}"
        if (cached_response := cache.get(cache_key)):
            logger.info(f"Cache hit for prompt: '{user_prompt}'. Returning cached response.")
            # We still need to save the history for this interaction
            ConversationHistory.objects.create(
                context_id=context_id, user_message=user_prompt, agent_message=cached_response
            )
            # Send the cached response back immediately
            send_response_to_webhook(cached_response, task_details)
            return

        logger.info("Cache miss. Proceeding with live agent execution.")
        
        # --- Step 2: Create and Run the Agent ---
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