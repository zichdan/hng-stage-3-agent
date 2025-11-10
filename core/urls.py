# core/urls.py
from django.contrib import admin
from django.urls import path, include
from .views import health_check

# drf-yasg imports for API documentation
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

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
)

urlpatterns = [
    # --- Django Admin ---
    path('admin/', admin.site.urls),
    
    # --- Health Check Endpoint ---
    path('kaithhealthcheck/', health_check, name='health_check'),
    
    # --- Core Application API ---
   #  path('api/v1/a2a/', include('a2a_protocol.urls')),
    path('api/v1/direct/', include('direct_agent.urls')),

    # --- API Documentation ---
    # This path makes the Swagger UI available at the root of your site
    path('', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]
