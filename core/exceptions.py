# core/exceptions.py
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


# Get a logger instance
logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django REST Framework.
    This formats all exceptions into a consistent JSON response.
    """
    # First, get the standard error response provided by DRF
    response = exception_handler(exc, context)

    # Log the full, detailed exception for debugging purposes
    logger.error(f"An unhandled exception occurred: {exc}", exc_info=True)

    if response is not None:
        # If DRF handled the exception, we re-format the response payload
        error_payload = {
            "error": "An error occurred",
            "details": response.data,
            "status_code": response.status_code
        }
        # Provide more user-friendly messages for common HTTP errors
        if response.status_code == status.HTTP_404_NOT_FOUND:
            error_payload["error"] = "Resource Not Found"
        elif response.status_code == status.HTTP_400_BAD_REQUEST:
            error_payload["error"] = "Invalid Request Parameters"
        elif response.status_code == status.HTTP_401_UNAUTHORIZED:
            error_payload["error"] = "Authentication Failed"
        
        response.data = error_payload
        return response

    # If DRF did not handle the exception, it's a 500 Internal Server Error
    # We create a generic, safe response to avoid leaking sensitive information.
    return Response(
        {
            "error": "Internal Server Error",
            "details": "An unexpected error occurred on our server. The technical team has been notified.",
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )