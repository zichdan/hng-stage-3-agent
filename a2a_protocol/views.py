# a2a_protocol/views.py
import logging
import uuid
from datetime import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from bs4 import BeautifulSoup # For cleaning HTML tags

# Import the serializer and the updated agent logic
from .serializers import JSONRPCRequestSerializer
from forex_agent.agent import get_agent_response_async

# Get a logger instance for this module
logger = logging.getLogger('a2a_protocol')

# ==============================================================================
# A2A ENDPOINT VIEW (ASYNCHRONOUS & BLOCKING)
# ==============================================================================
# This view now correctly handles the full async request-response lifecycle,
# resolving the 'coroutine was never awaited' error.
# ==============================================================================

class A2AEndpointView(APIView):
    """
    The main API endpoint that receives, processes, and returns
    A2A protocol requests in a single, blocking call.
    """

    async def dispatch(self, request, *args, **kwargs):
        """
        CORRECTED: Overrides the default synchronous dispatch method to correctly
        handle async POST requests and await the handler.
        """
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers

        try:
            self.initial(request, *args, **kwargs)

            if request.method.lower() in self.http_method_names:
                handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed

            # This is the critical change: we now AWAIT the async handler.
            response = await handler(request, *args, **kwargs)

        except Exception as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response

    async def post(self, request, agent_name: str):
        """
        Handles incoming POST requests from platforms like Telex.im.
        """
        logger.info(f"Received A2A request for agent: '{agent_name}'")
        logger.debug(f"Request Body: {request.data}")

        # --- Step 1: Validate the incoming request ---
        serializer = JSONRPCRequestSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as validation_error:
            logger.warning(f"Invalid A2A request: {validation_error}")
            return Response({
                "jsonrpc": "2.0",
                "id": request.data.get('id'),
                "error": { "code": -32602, "message": "Invalid params", "data": serializer.errors }
            }, status=status.HTTP_400_BAD_REQUEST)
        
        validated_data = serializer.validated_data
        params = validated_data['params']
        
        # --- Step 2: Extract User Prompt and History from Parts Array ---
        user_prompt = None
        chat_history_from_request = []
        try:
            parts = params['message']['parts']

            # The first part is the system-interpreted prompt
            text_part = next((p for p in parts if p.get('kind') == 'text'), None)
            if text_part and 'text' in text_part:
                user_prompt = text_part['text']
            
            # The second part contains the conversation history
            data_part = next((p for p in parts if p.get('kind') == 'data'), None)
            if data_part and 'data' in data_part:
                chat_history_from_request = data_part['data']

            if user_prompt is None:
                raise ValueError("No valid 'text' part found for the user prompt.")
            
            # Clean potential HTML tags from the prompt, just in case
            soup = BeautifulSoup(user_prompt, 'html.parser')
            cleaned_prompt = soup.get_text()
            if cleaned_prompt != user_prompt:
                logger.debug(f"Cleaned prompt from '{user_prompt}' to '{cleaned_prompt}'")
                user_prompt = cleaned_prompt
            
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.error(f"Could not extract user prompt or history from parts array: {e}")
            return Response({
                "jsonrpc": "2.0",
                "id": validated_data.get('id'),
                "error": {"code": -32602, "message": "Invalid params", "data": f"Could not parse message.parts array. Error: {e}"}
            }, status=status.HTTP_400_BAD_REQUEST)

        # --- Step 3: Prepare Agent Call ---
        context_id = params.get('contextId') or str(uuid.uuid4())

        # --- Step 4: Route and Execute Agent Logic ---
        if agent_name == "forex-compass":
            logger.debug(f"Executing agent directly for context_id: {context_id} with prompt: '{user_prompt}'")
            
            # Await the response from the agent's core logic, now passing the history
            agent_response_text = await get_agent_response_async(user_prompt, context_id, chat_history_from_request)

            final_state = "failed" if "I'm sorry, I encountered an internal error" in agent_response_text else "completed"

        else:
            # Agent not found (No change)
            logger.warning(f"Request received for an unknown agent: '{agent_name}'")
            return Response({
                "jsonrpc": "2.0",
                "id": validated_data['id'],
                "error": {"code": -32601, "message": f"Method not found: Agent '{agent_name}' not found."}
            }, status=status.HTTP_404_NOT_FOUND)

        # --- Step 5: Immediately Return the Final, Correctly Formatted Response ---
        logger.info(f"Successfully generated direct response for request_id: {validated_data['id']}.")
        
        response_payload = {
            "jsonrpc": "2.0",
            "id": validated_data['id'],
            "result": {
                "id": params['taskId'],
                "contextId": context_id,
                "status": {
                    "state": final_state,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "message": {
                        "kind": "message", "role": "agent",
                        "parts": [{"kind": "text", "text": agent_response_text}]
                    }
                },
                "kind": "task"
            }
        }
        
        return Response(response_payload, status=status.HTTP_200_OK)