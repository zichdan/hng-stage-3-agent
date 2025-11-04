# core/views.py
from django.http import JsonResponse

def health_check(request):
    """
    A simple health check endpoint that returns a 200 OK response.
    This is used by hosting platforms like Leapcell to verify that the
    service is running and responsive.
    """
    return JsonResponse({"status": "healthy", "message": "Forex Compass AI Agent is running."})