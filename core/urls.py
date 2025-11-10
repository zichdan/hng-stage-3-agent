# core/urls.py

from django.contrib import admin
from django.urls import path, include
from .views import health_check

# drf-yasg imports for API documentation
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

# ==============================================================================
# THE FIX: Define your API URL patterns in a separate list.
# ==============================================================================
# This tells drf-yasg exactly which patterns to generate documentation for.
api_urlpatterns = [
    path('api/v1/a2a/', include('direct_agent.urls')),
]
# ==============================================================================

# This sets up the metadata for your API documentation
schema_view = get_schema_view(
   openapi.Info(
      title="Forex Compass AI Agent API",
      default_version='v1',
      description="API documentation for the Forex Compass AI Agent. This API handles asynchronous agent-to-agent (A2A) interactions for providing forex education and market news to beginner traders.",
      contact=openapi.Contact(email="contact@forexcompass.ai"),
      license=openapi.License(name="MIT License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
   patterns=api_urlpatterns,  # <--- THE FIX: Explicitly pass the API patterns here.
)

urlpatterns = [
    # --- Django Admin ---
    path('admin/', admin.site.urls),
    
    # --- Health Check Endpoint ---
    path('kaithhealthcheck/', health_check, name='health_check'),
    
    # --- API Documentation ---
    # These URLs now serve the documentation generated ONLY from `api_urlpatterns`.
    path('', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    
] + api_urlpatterns # <--- THE FIX: Add the API patterns to the main urlpatterns so they are live.