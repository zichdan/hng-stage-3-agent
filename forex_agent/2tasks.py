# ... (keep all the existing code from the previous step)

# ==============================================================================
# 4. ON-DEMAND REACTIVE ENGINE (Handles User Prompts)
# ==============================================================================
# This is the task that is triggered in real-time when a user sends a message.
# It orchestrates the entire response generation process, from caching and
# vector search to the final LLM call and webhook delivery.
# ==============================================================================
from django.core.cache import cache
from .models import ConversationHistory
from .agent_logic import ForexCompassAgent # We will create this file next

@shared_task(name="handle_user_prompt_task", acks_late=True)
def handle_user_prompt_task(task_details: dict):
    """
    The main on-demand task that handles a user's prompt from start to finish.
    """
    user_prompt = task_details['user_prompt']
    context_id = task_details.get('context_id')
    
    logger.info(f"Handling user prompt for context_id '{context_id}': '{user_prompt}'")
    
    try:
        # --- Step 1: Check Cache ---
        # For frequently asked questions, this provides a near-instant response.
        cache_key = f"forex_compass_response:{user_prompt}"
        cached_response = cache.get(cache_key)
        if cached_response:
            logger.info(f"Cache hit for prompt. Returning cached response for task {task_details['task_id']}.")
            # We still need to save this to history for conversation flow
            ConversationHistory.objects.create(
                context_id=context_id,
                user_message=user_prompt,
                agent_message=cached_response
            )
            send_final_response(cached_response, task_details)
            return

        # --- Step 2: Initialize and run the core agent logic ---
        # The complex logic (RAG, LLM calls) is encapsulated in the agent class.
        agent = ForexCompassAgent(context_id=context_id)
        final_answer = agent.get_response(user_prompt)

        # --- Step 3: Save to History and Cache ---
        if final_answer:
            logger.info(f"Generated new response for task {task_details['task_id']}. Caching and saving to history.")
            # Save the new user-agent interaction to the database for long-term context.
            ConversationHistory.objects.create(
                context_id=context_id,
                user_message=user_prompt,
                agent_message=final_answer
            )
            # Cache the new response for 10 minutes to handle repeat questions quickly.
            cache.set(cache_key, final_answer, timeout=600)
        else:
            logger.error(f"Agent failed to generate a response for task {task_details['task_id']}.")
            final_answer = "I'm sorry, I encountered an issue and couldn't generate a response. Please try asking in a different way."

        # --- Step 4: Send the final response back to the user ---
        send_final_response(final_answer, task_details)

    except Exception as e:
        logger.critical(f"A critical error occurred in handle_user_prompt_task for task {task_details['task_id']}: {e}", exc_info=True)
        error_message = "I'm sorry, a server error occurred while processing your request. Please try again later."
        send_final_response(error_message, task_details, state="failed")


def send_final_response(answer: str, task_details: dict, state: str = "completed"):
    """
    Helper function to format the final A2A TaskResult and POST it to the
    webhook URL provided in the initial request.
    """
    webhook_config = task_details['webhook_config']
    if not webhook_config or 'url' not in webhook_config:
        logger.error(f"No webhook URL provided for task {task_details['task_id']}. Cannot send response.")
        return

    # Construct the final payload according to the A2A protocol for async tasks.
    response_payload = {
        "jsonrpc": "2.0",
        "id": task_details['request_id'],
        "result": {
            "id": task_details['task_id'],
            "contextId": task_details.get('context_id'),
            "status": {
                "state": state,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "message": {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": answer}]
                }
            },
            "kind": "task"
        }
    }
    
    # In case of failure, we structure the error correctly.
    if state == "failed":
        response_payload = {
            "jsonrpc": "2.0",
            "id": task_details['request_id'],
            "error": {"code": -32603, "message": "Internal Agent Error", "data": {"details": answer}}
        }

    try:
        headers = {'Content-Type': 'application/json'}
        with httpx.Client() as client:
            response = client.post(webhook_config['url'], json=response_payload, headers=headers, timeout=20.0)
            response.raise_for_status()
            logger.info(f"Successfully sent final response to webhook for task {task_details['task_id']}")
    except httpx.RequestError as e:
        logger.error(f"Failed to send final response to webhook for task {task_details['task_id']}: {e}")