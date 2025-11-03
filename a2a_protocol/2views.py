# a2a_protocol/views.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import A2ARequestSerializer
# Import the on-demand task we are about to create.
from forex_agent.tasks import handle_user_prompt_task

logger = logging.getLogger('a2a_protocol')

class A2AEndpointView(APIView):
    """
    The main entry point for all A2A protocol requests from Telex.im.
    This view is designed to be asynchronous and non-blocking. It validates
    the request and immediately dispatches a background task to handle the
    heavy processing, ensuring a fast response to the caller.
    """
    def post(self, request, agent_name: str, *args, **kwargs):
        try:
            # --- Step 1: Route to the correct agent ---
            # This structure allows you to easily add more agents in the future.
            if agent_name != "forex-compass":
                logger.warning(f"Request made to an unknown agent: '{agent_name}'")
                return Response(
                    {"error": f"Agent '{agent_name}' not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # --- Step 2: Validate the incoming request data ---
            serializer = A2ARequestSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error(f"Invalid A2A request received: {serializer.errors}")
                return Response(
                    {"error": "Invalid request parameters.", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- Step 3: Extract data and dispatch the background task ---
            valid_data = serializer.validated_data
            params = valid_data['params']
            
            # Consolidate all necessary details into a single dictionary for the task.
            task_details = {
                "request_id": valid_data['id'],
                "task_id": params['taskId'],
                "context_id": params.get('contextId'),
                "user_prompt": params['message']['parts'][0]['text'],
                "webhook_config": params['configuration']['pushNotificationConfig'],
            }

            logger.info(f"Dispatching task {task_details['task_id']} for agent '{agent_name}'.")
            
            # Use `.delay()` to send the task to the Celery queue.
            # The actual work will be done by a Celery worker process.
            handle_user_prompt_task.delay(task_details)

            # --- Step 4: Immediately acknowledge the request ---
            # According to async best practices, we immediately tell the caller
            # that we've accepted the request and are working on it.
            return Response({
                "jsonrpc": "2.0",
                "id": valid_data['id'],
                "result": {
                    "status": "processing",
                    "message": "Task accepted and is being processed in the background."
                }
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.critical(f"A critical unhandled error occurred in the A2A endpoint: {e}", exc_info=True)
            return Response(
                {"error": "An unexpected server error occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )