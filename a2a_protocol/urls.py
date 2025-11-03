# a2a_protocol/urls.py
from django.urls import path
from .views import A2AEndpointView

urlpatterns = [
    # This single pattern will capture the agent's name from the URL.
    # e.g., /api/v1/a2a/forex-compass -> agent_name = "forex-compass"
    path('<str:agent_name>', A2AEndpointView.as_view(), name='a2a-endpoint'),
]