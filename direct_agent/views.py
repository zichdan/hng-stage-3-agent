# direct_agent/views.py

import logging
import uuid
import json
from datetime import datetime
import asyncio
import httpx

from asgiref.sync import sync_to_async
from bs4 import BeautifulSoup
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

# --- drf-yasg Imports for Manual Schema ---
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

# Import the shared serializer for consistent validation.
from a2a_protocol.serializers import JSONRPCRequestSerializer

# Import the model for saving history and the new async service.
from forex_agent.models import ConversationHistory
from .services import get_gemini_direct_response

# Get a logger instance for this module
logger = logging.getLogger('direct_agent')

# ==============================================================================
# FINAL, A2A-COMPLIANT IMPLEMENTATION
# ==============================================================================
class A2ADirectEndpointView(APIView):
    """
    An A2A-compliant APIView that handles all requests in a blocking fashion
    and formats the response according to the A2A Task object specification.
    """

    # This is the correct way to make a DRF APIView handle async logic.
    # We override dispatch to handle the entire request-response cycle asynchronously.
    async def dispatch(self, request, *args, **kwargs):
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
            
            # The handler (e.g., self.post) is an async method, so we await it.
            response = await handler(request, *args, **kwargs)

        except Exception as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response

    @swagger_auto_schema(
        operation_summary="Send a message to an AI Agent (Direct)",
        operation_description="This endpoint is the primary communication channel for interacting with an AI agent using the A2A (Agent-to-Agent) protocol. It accepts a standard JSON-RPC 2.0 request.",
        tags=['A2A Protocol'],
        request_body=JSONRPCRequestSerializer,
        responses={
            200: openapi.Response(
                description="Successful AI agent response.",
                examples={"application/json": {"jsonrpc": "2.0", "id": "req-123", "result": {"id": "task-123", "status": {"state": "completed"}}}}
            ),
            400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"
        }
    )
    async def post(self, request, agent_name: str):
        """
        Handles a POST request, validates it, calls the Gemini service,
        persists the interaction, and returns a fully A2A-compliant response.
        """
        request_id = "N/A"
        try:
            # --- Step 0: Initial Request Ingestion & Logging ---
            logger.info(f"Received direct A2A request for agent: '{agent_name}'")
            data = request.data
            request_id = data.get('id', 'N/A')
            logger.debug(f"Request ID '{request_id}': Body: {data}")

            # --- Step 1: Validate the Incoming Request ---
            serializer = JSONRPCRequestSerializer(data=data)
            # Use a try-except block for DRF's validation
            try:
                serializer.is_valid(raise_exception=True)
            except ValidationError as exc:
                logger.warning(f"Request ID '{request_id}': Invalid A2A request: {exc.detail}")
                error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params", "data": exc.detail}}
                return Response(error_payload, status=status.HTTP_400_BAD_REQUEST)
                
            validated_data = serializer.validated_data
            params = validated_data['params']

            # --- Step 2: Extract and Clean User Prompt & History ---
            try:
                parts = params['message']['parts']
                text_part = next((p for p in parts if p.get('kind') == 'text'), {})
                data_part = next((p for p in parts if p.get('kind') == 'data'), {})
                
                user_prompt = text_part.get('text')
                chat_history_from_request = data_part.get('data', [])

                if not user_prompt:
                    raise ValueError("No valid 'text' part found for the user prompt.")
                
                soup = BeautifulSoup(user_prompt, 'html.parser')
                cleaned_prompt = soup.get_text()
                if cleaned_prompt != user_prompt:
                    logger.debug(f"Request ID '{request_id}': Cleaned prompt from '{user_prompt}' to '{cleaned_prompt}'")
                    user_prompt = cleaned_prompt
                
            except (KeyError, IndexError, TypeError, ValueError) as e:
                logger.error(f"Request ID '{request_id}': Could not extract prompt/history from parts array: {e}", exc_info=True)
                error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params", "data": f"Could not parse message.parts array. Error: {e}"}}
                return Response(error_payload, status=status.HTTP_400_BAD_REQUEST)

            # --- Step 3: Prepare Agent Call ---
            context_id = params.get('contextId') or str(uuid.uuid4())
            task_id = params.get('taskId', str(uuid.uuid4()))

            # --- Step 4: Route and Execute Agent Logic ---
            if agent_name == "forex-compass":
                logger.debug(f"Request ID '{request_id}': Executing direct agent for context_id: {context_id}...")
                agent_response_text = await get_gemini_direct_response(user_prompt, chat_history_from_request)
                final_state = "failed" if "I'm sorry, I encountered" in agent_response_text else "completed"
            else:
                logger.warning(f"Request ID '{request_id}': Request received for an unknown agent: '{agent_name}'")
                error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: Agent '{agent_name}' not found."}}
                return Response(error_payload, status=status.HTTP_404_NOT_FOUND)

            # --- Step 5: Persist Conversation History (Safely) ---
            try:
                await sync_to_async(ConversationHistory.objects.create)(
                    context_id=context_id, user_message=user_prompt, agent_message=agent_response_text
                )
                logger.info(f"Request ID '{request_id}': Successfully saved conversation history for context_id '{context_id}'.")
            except Exception as db_error:
                logger.error(f"Request ID '{request_id}': Failed to save conversation history. DB Error: {db_error}", exc_info=True)

            # ======================================================================
            # THE FINAL FIX: Construct a fully A2A-compliant response object
            # ======================================================================
            logger.info(f"Request ID '{request_id}': Successfully generated and returning A2A-compliant direct response.")
            
            response_payload = {
                "jsonrpc": "2.0",
                "id": validated_data['id'],
                "result": {
                    "id": task_id,
                    "contextId": context_id,
                    "status": {
                        "state": final_state,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "message": {
                            "messageId": str(uuid.uuid4()),
                            "role": "agent",
                            "parts": [
                                {
                                    "kind": "text",
                                    "text": "Here is the information you requested." # A concise status message
                                }
                            ],
                            "kind": "message"
                        }
                    },
                    "artifacts": [
                        {
                            "artifactId": str(uuid.uuid4()),
                            "name": "agentResponse",
                            "parts": [
                                {
                                    "kind": "text",
                                    "text": agent_response_text # The full, detailed AI response
                                }
                            ]
                        }
                    ],
                    "history": [], # You can optionally populate this if needed
                    "kind": "task"
                }
            }
            return Response(response_payload, status=status.HTTP_200_OK)

        except Exception as e:
            # Top-level catch-all for validation errors or other unhandled exceptions.
            logger.critical(f"Request ID '{request_id}': An unhandled exception occurred in the direct view: {e}", exc_info=True)
            error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal error", "data": str(e)}}
            return Response(error_payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Create a single instance of the view for the URL router
a2a_direct_endpoint = A2ADirectEndpointView.as_view()












































































# # direct_agent/views.py

# import logging
# import uuid
# import json
# from datetime import datetime

# from asgiref.sync import sync_to_async
# from bs4 import BeautifulSoup
# from django.http import JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# from django.views.decorators.http import require_POST

# # Import the shared serializer for consistent validation.
# from a2a_protocol.serializers import JSONRPCRequestSerializer

# # Import the model for saving history and the new async service.
# from forex_agent.models import ConversationHistory
# from .services import get_gemini_direct_response

# # Get a logger instance for this module
# logger = logging.getLogger('direct_agent')

# # ==============================================================================
# # DIRECT A2A ENDPOINT (HIGH-PERFORMANCE ASYNC FUNCTION)
# # ==============================================================================
# # This endpoint is designed for maximum performance and reliability. It bypasses
# # the RAG pipeline and communicates directly with the Gemini LLM.
# # ==============================================================================

# @csrf_exempt
# @require_POST
# async def a2a_direct_endpoint(request, agent_name: str):
#     """
#     Handles a POST request, validates it against the A2A protocol, calls the
#     direct Gemini service, persists the interaction, and returns a formatted response.
#     """
#     request_id = "N/A"
#     try:
#         # --- Step 0: Initial Request Ingestion & Logging ---
#         logger.info(f"Received direct A2A request for agent: '{agent_name}'")
#         request_body = request.body
#         data = json.loads(request_body)
#         request_id = data.get('id', 'N/A')
#         logger.debug(f"Request ID '{request_id}': Body: {data}")

#         # --- Step 1: Validate the Incoming Request ---
#         serializer = JSONRPCRequestSerializer(data=data)
#         serializer.is_valid(raise_exception=True)
#         validated_data = serializer.validated_data
#         params = validated_data['params']

#         # --- Step 2: Extract and Clean User Prompt & History ---
#         try:
#             parts = params['message']['parts']
#             text_part = next((p for p in parts if p.get('kind') == 'text'), {})
#             data_part = next((p for p in parts if p.get('kind') == 'data'), {})
            
#             user_prompt = text_part.get('text')
#             chat_history_from_request = data_part.get('data', [])

#             if not user_prompt:
#                 raise ValueError("No valid 'text' part found for the user prompt.")
            
#             soup = BeautifulSoup(user_prompt, 'html.parser')
#             cleaned_prompt = soup.get_text()
#             if cleaned_prompt != user_prompt:
#                 logger.debug(f"Request ID '{request_id}': Cleaned prompt from '{user_prompt}' to '{cleaned_prompt}'")
#                 user_prompt = cleaned_prompt
            
#         except (KeyError, IndexError, TypeError, ValueError) as e:
#             logger.error(f"Request ID '{request_id}': Could not extract prompt/history from parts array: {e}", exc_info=True)
#             error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params", "data": f"Could not parse message.parts array. Error: {e}"}}
#             return JsonResponse(error_payload, status=400)

#         # --- Step 3: Prepare Agent Call ---
#         context_id = params.get('contextId') or str(uuid.uuid4())

#         # --- Step 4: Route and Execute Agent Logic ---
#         if agent_name == "forex-compass":
#             logger.debug(f"Request ID '{request_id}': Executing direct agent for context_id: {context_id}...")
#             agent_response_text = await get_gemini_direct_response(user_prompt, chat_history_from_request)
#             final_state = "failed" if "I'm sorry, I encountered" in agent_response_text else "completed"
#         else:
#             logger.warning(f"Request ID '{request_id}': Request received for an unknown agent: '{agent_name}'")
#             error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: Agent '{agent_name}' not found."}}
#             return JsonResponse(error_payload, status=404)

#         # --- Step 5: Persist Conversation History (Safely) ---
#         try:
#             await sync_to_async(ConversationHistory.objects.create)(
#                 context_id=context_id, user_message=user_prompt, agent_message=agent_response_text
#             )
#             logger.info(f"Request ID '{request_id}': Successfully saved conversation history for context_id '{context_id}'.")
#         except Exception as db_error:
#             # CRITICAL: Log the database error but do not fail the request.
#             # Returning the response to the user is the highest priority.
#             logger.error(f"Request ID '{request_id}': Failed to save conversation history. DB Error: {db_error}", exc_info=True)

#         # --- Step 6: Return the Final, Formatted Response ---
#         logger.info(f"Request ID '{request_id}': Successfully generated and returning direct response.")
#         response_payload = {
#             "jsonrpc": "2.0", "id": validated_data['id'],
#             "result": {
#                 "id": params['taskId'], "contextId": context_id,
#                 "status": {
#                     "state": final_state, "timestamp": datetime.utcnow().isoformat() + "Z",
#                     "message": {"kind": "message", "role": "agent", "parts": [{"kind": "text", "text": agent_response_text}]}
#                 },
#                 "kind": "task"
#             }
#         }
#         return JsonResponse(response_payload, status=200)

#     except json.JSONDecodeError:
#         logger.warning("Failed to decode JSON from request body.")
#         return JsonResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status=400)

#     except Exception as e:
#         # Top-level catch-all for validation errors or other unhandled exceptions.
#         logger.critical(f"Request ID '{request_id}': An unhandled exception occurred in the direct view: {e}", exc_info=True)
#         error_payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal error", "data": str(e)}}
#         return JsonResponse(error_payload, status=500)