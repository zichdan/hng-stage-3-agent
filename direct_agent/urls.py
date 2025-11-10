# direct_agent/urls.py

from django.urls import path
from . import views

# ==============================================================================
# URL PATTERNS FOR THE DIRECT AGENT APP
# ==============================================================================

urlpatterns = [
    # This URL pattern captures the agent's name and passes it to our async view.
    # Example URL: /api/v1/direct/agent/forex-compass/
    path('<str:agent_name>', views.a2a_direct_endpoint, name='a2a_direct_endpoint'),
]