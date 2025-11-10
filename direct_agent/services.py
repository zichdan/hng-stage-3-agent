# direct_agent/services.py

import logging
import httpx
from typing import List, Dict, Any
from decouple import config

from .instructions import GEMINI_AGENT_INSTRUCTIONS

# Get a logger instance for this module
logger = logging.getLogger('direct_agent')

# ==============================================================================
# SERVICE-LEVEL CONFIGURATION
# ==============================================================================

# --- API Configuration ---
# Fetch the API key securely.
GEMINI_API_KEY = config('GEMINI_API_KEY', default=None)

# --- THE FIX: Use a valid model name confirmed by your check_models.py script ---
# This is the primary solution to the 404 error.
VALID_GEMINI_MODEL = "gemini-2.0-flash-001" 

# Define the API endpoint at the module level for clarity and ease of maintenance.
# GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{VALID_GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

# --- Production-Ready Timeout Configuration ---
# A generous timeout is crucial for generative AI calls.
# 10s to establish a connection, 180s (3 minutes) to wait for a full response.
API_TIMEOUTS = httpx.Timeout(10.0, read=180.0)


# ==============================================================================
# ASYNCHRONOUS GEMINI API SERVICE
# ==============================================================================
# This service encapsulates all logic for communicating with the external
# Google Gemini API, ensuring the view layer remains clean and focused.
# ==============================================================================

async def get_gemini_direct_response(user_prompt: str, chat_history_from_request: List[Dict[str, Any]]) -> str:
    """
    Asynchronously and safely calls the Google Gemini API with a constructed
    prompt, conversation history, and exhaustive error handling.

    Args:
        user_prompt (str): The user's current question.
        chat_history_from_request (List[Dict]): The raw history list from the A2A request.

    Returns:
        str: The text response from the Gemini API, or a user-friendly error message.
    """
    if not GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY is not configured. The direct agent cannot function.")
        return "I'm sorry, my core AI service is not configured correctly. The administrator has been notified."

    # --- Step 1: Construct the 'contents' payload for the Gemini API ---
    # This format is required for multi-turn conversations.
    contents = []
    
    # Add the main system instructions.
    contents.append({"role": "user", "parts": [{"text": GEMINI_AGENT_INSTRUCTIONS}]})
    
    # Prime the model with an ideal response to reinforce its instructions.
    contents.append({"role": "model", "parts": [{"text": "Understood. I am Forex Compass, an educational AI mentor. I will strictly adhere to my rules and never provide financial advice."}]})
    
    # Add the conversation history, correctly alternating roles.
    for i, msg in enumerate(chat_history_from_request):
        text = msg.get('text', '').replace('<p>', '').replace('</p>', '')
        # Assign roles based on the message index (assuming user, agent, user, agent...).
        role = "user" if i % 2 == 0 else "model"
        contents.append({"role": role, "parts": [{"text": text}]})

    # Finally, add the current user's prompt.
    contents.append({"role": "user", "parts": [{"text": user_prompt}]})

    # --- Step 2: Define the full request payload ---
    request_payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        }
    }

    # --- Step 3: Make the Asynchronous API Call with Comprehensive Error Handling ---
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUTS) as client:
            logger.info("Sending direct request to Gemini API...")
            
            response = await client.post(GEMINI_API_URL, json=request_payload)
            
            # This is the most reliable way to check for API errors.
            response.raise_for_status()
            
            response_data = response.json()
            
            # Safely extract the content, guarding against unexpected API response structures.
            content = response_data['candidates'][0]['content']['parts'][0]['text']
            
            logger.info("Successfully received and parsed response from Gemini API.")
            return content

    except httpx.TimeoutException:
        logger.error("Gemini API request timed out after 180 seconds.", exc_info=True)
        return "I'm sorry, the request to my AI core took too long to complete. Please try again in a moment."

    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        logger.error(f"Gemini API returned a non-200 status: {e.response.status_code}. Body: {error_body}", exc_info=True)
        return f"I'm sorry, I encountered an API error ({e.response.status_code}) while processing your request."

    except httpx.RequestError as e:
        logger.error(f"A network error occurred while calling Gemini API: {e}", exc_info=True)
        return "I'm sorry, I'm having trouble connecting to my knowledge source. Please check the network connection or try again later."
        
    except (KeyError, IndexError, TypeError):
        # This handles cases where the Gemini response structure is malformed.
        logger.error("Could not parse the expected structure from Gemini API response.", exc_info=True)
        logger.debug(f"Malformed Gemini Response Body: {locals().get('response_data', 'Not available')}")
        return "I'm sorry, I received an unexpected response from my AI service. I cannot process your request at this moment."

    except Exception:
        logger.critical("An unexpected critical error occurred in the Gemini service.", exc_info=True)
        return "I'm sorry, I encountered a critical internal error. Please try again in a moment."