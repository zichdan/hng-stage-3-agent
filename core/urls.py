# core/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # All A2A requests will be routed through this path.
    path('api/v1/a2a/', include('a2a_protocol.urls')),
]
