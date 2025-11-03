# a2a_protocol/views.py
import logging
import uuid
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# Import the serializer for validation and the Celery task to be dispatched.
from .serializers import JSONRPCRequestSerializer
from forex_agent.agent import process_user_query # Correctly import the task

# Get a logger instance for this module
logger = logging.getLogger('a2a_protocol')

# ==============================================================================
# A2A ENDPOINT VIEW
# ==============================================================================
# This single, generic view is the entry point for all A2A agents.
# It uses the URL to determine which agent's task to dispatch, making the
# system highly extensible for future agents (e.g., 'fashion-stylist').
# ==============================================================================

class A2AEndpointView(APIView):
    """
    The main API endpoint that receives and dispatches A2A protocol requests.
    """
    def post(self, request, agent_name: str):
        """
        Handles incoming POST requests from platforms like Telex.im.
        """
        logger.info(f"Received A2A request for agent: '{agent_name}'")

        # --- Step 1: Validate the incoming request against our serializer ---
        # If the data is invalid, DRF's raise_exception=True handles it,
        # which our custom exception handler formats into a clean 400 Bad Request.
        serializer = JSONRPCRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # If validation passes, we can safely access the data.
        validated_data = serializer.validated_data
        params = validated_data['params']
        
        try:
            user_prompt = params['message']['parts'][0]['text']
        except (KeyError, IndexError):
            logger.error("Request is valid but is missing the user prompt text.")
            return Response(
                {"error": "Invalid Message Structure", "details": "The 'message.parts' array must contain at least one text part."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Step 2: Prepare a dictionary of all necessary details for the background task ---
        # This keeps our Celery task signature clean and makes it easy to pass more data in the future.
        task_details = {
            "request_id": validated_data['id'],
            "task_id": params['taskId'],
            # If a contextId isn't provided for a new conversation, we generate a new UUID.
            "context_id": params.get('contextId') or str(uuid.uuid4()),
            "webhook_config": params['configuration']['pushNotificationConfig'],
            "user_prompt": user_prompt
        }

        # --- Step 3: Route the request to the correct agent's Celery task ---
        # This simple routing logic makes it easy to add more agents in the future.
        if agent_name == "forex-compass":
            logger.debug(f"Dispatching task to 'process_user_query' for context_id: {task_details['context_id']}")
            # The `.delay()` method sends the task to the Celery queue to be processed by a worker.
            # This is a non-blocking call; it returns immediately.
            process_user_query.delay(task_details)
        else:
            # If the URL contains an unknown agent name, return a 404 Not Found.
            logger.warning(f"Request received for an unknown agent: '{agent_name}'")
            return Response({"error": f"Agent '{agent_name}' not found."}, status=status.HTTP_404_NOT_FOUND)

        # --- Step 4: Immediately Acknowledge the Request ---
        # We instantly return a 202 Accepted response. This tells Telex.im that we have
        # received the request and are working on it. This is crucial for a responsive
        # asynchronous architecture and prevents timeouts on the Telex side.
        logger.info(f"Successfully dispatched task for request_id: {validated_data['id']}. Returning 202 Accepted.")
        return Response({
            "jsonrpc": "2.0",
            "id": validated_data['id'],
            "result": {
                "id": params['taskId'],
                "contextId": task_details['context_id'],
                "status": {
                    "state": "working",
                    "message": "Task accepted and is being processed in the background."
                }
            }
        }, status=status.HTTP_202_ACCEPTED)
