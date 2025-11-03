# forex_agent/agent.py
import logging
from decouple import config
from langchain_openai import ChatOpenAI

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage

from .models import ConversationHistory
from .tools import knowledge_base_search, get_latest_market_news

# Get a logger instance for this module, as configured in settings.py
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

    1.  **Use Your Tools:** You have access to `knowledge_base_search` for forex concepts and `get_latest_market_news` for news. You should ALWAYS prefer to use these tools to answer questions.
    2.  **NEVER Give Financial Advice:** You must NEVER predict market movements, suggest specific trades (e.g., "should I buy EUR/USD?"), or give any form of financial advice.
    3.  **Safety First:** If a user's question is close to asking for financial advice, you MUST politely decline and explicitly state: 'Disclaimer: I am an AI assistant and cannot provide financial advice. My purpose is purely educational. Please consult a qualified financial professional for investment advice.'
    4.  **Answer from Context:** When your tools provide information, base your final answer primarily on that information to ensure accuracy and safety.
    5.  **Be a Mentor:** Keep your tone simple, encouraging, and clear. Explain complex topics in a way a complete beginner can understand. If you don't have an answer, it's better to say so and offer to explain a related concept. Maintain an encouraging and supportive tone.
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
    This function is called by the Celery task for each new user request.
    """
    # ==============================================================================
    # THE FIX: DEFERRED IMPORT
    # Move the heavy import inside the function. This prevents it from running
    # during Django's startup, avoiding the import conflict.
    # ==============================================================================
    from langchain.agents import AgentExecutor, create_openai_tools_agent

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
        # `create_openai_tools_agent` binds the LLM, tools, and prompt together into a runnable agent.
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