# core/settings.py
import os
from pathlib import Path
import sys
from environs import Env
from decouple import config
from celery.schedules import crontab
import dj_database_url




# ==============================================================================
# CORE PATHS & CONFIGURATION
# ==============================================================================

# Initialize Env for reading .env file
env = Env()
env.read_env() # Reads the .env file

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Get SECRET_KEY from environment variable
SECRET_KEY = env("SECRET_KEY", default='django-insecure-b*tuoe%^o+=^35$0fufrm=oamh^(o0tabn39(7ni12(i-oup+4') # Fallback for local, but ensure it's set in .env for production


# SECURITY WARNING: don't run with debug turned on in production!
# Get DEBUG from environment variable
DEBUG = env.bool("DEBUG", default=True) # Default to True for local, set to False in .env for production

# Site URL
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000")

DJANGO_SECRET_ADMIN_URL=env("DJANGO_SECRET_ADMIN_URL", default="admin/")

# ALLOWED_HOSTS from environment variable, split by comma
# For production, specify your Render URL and any other hostnames.
# For local, '127.0.0.1' and 'localhost' are usually sufficient.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost", "localhost:8000", "localhost:3001"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=['http://localhost:3000', 'http://localhost:8000'])
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'

CORS_ALLOW_ALL_ORIGINS = True



# ==============================================================================
# APPLICATION DEFINITION
# ==============================================================================

INSTALLED_APPS = [
    # ASGI Server (must be first for Channels)
    'daphne',
    
    # Django Core Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',

    
    # =================================================================================
    # Whitenoise must be listed before 'django.contrib.staticfiles' 
    'whitenoise.runserver_nostatic',  # For serving static files in development
    'django.contrib.staticfiles',
    # =================================================================================


    # Third-Party Apps
    'corsheaders',
    'rest_framework',
    'drf_yasg',
    'django_celery_beat',
    'pgvector',           # Enables vector field support in PostgreSQL

    # Local Apps
    'a2a_protocol',
    'forex_agent',
    'direct_agent',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # For efficient static file serving

    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application' # For Channels

# ==============================================================================
# DATABASE
# ==============================================================================
# Uses dj-database-url to parse the DATABASE_URL from .env.
# This single line handles connection pooling, SSL, and different database backends.
DATABASES = {
    'default': dj_database_url.config(
        # Use the DATABASE_URL from the environment, fall back to SQLite for local dev
        default='sqlite:///' + os.path.join(BASE_DIR, 'db.sqlite3'),
        conn_max_age=600 # Keep connections alive for 10 minutes
    )
}

# ==============================================================================
# CACHING (with Redis)
# ==============================================================================
# Used for Celery, caching API responses, and session management.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config('REDIS_URL', default="redis://127.0.0.1:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# ==============================================================================
# ASYNCHRONOUS TASKS & SCHEDULING (Celery & Celery Beat)
# ==============================================================================
CELERY_BROKER_URL = config('REDIS_URL', default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = config('REDIS_URL', default="redis://127.0.0.1:6379/0") # CELERY_RESULT_BACKEND = 'django-db' # Store task results in the Django database

# Core settings
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'          # Can be 'UTC' or 'Africa/Lagos'


# Production-ready settings Task routing & reliability
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_TRACK_STARTED = True
CELERY_ACKS_LATE = True  # Ensures tasks aren't lost if a worker process crashes before completing.  # The task is only acknowledged *after* it has successfully finished.
CELERYD_PREFETCH_MULTIPLIER = 1  # prevent task duplication
CELERY_TASK_REJECT_ON_WORKER_LOST = True



# # Retry and connection handling (production safe)
# CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# CELERY_BROKER_CONNECTION_TIMEOUT = 30
# CELERY_BROKER_TRANSPORT_OPTIONS = {
#     "visibility_timeout": 3600,         # 1hr task visibility
#     "socket_timeout": 30,               # network read timeout
#     "socket_connect_timeout": 30,       # initial connection timeout
#     "retry_on_timeout": True,
#     "max_connections": 20,              # limit connections
#     "ssl_cert_reqs": None, # Important for rediss schemes if not using full cert validation
# }




# Defines the schedule for our proactive knowledge-gathering tasks.
# This schedule is now fully decoupled and staggered.
# CORRECTED: Tasks are now scheduled separately and offset to prevent bursts.
CELERY_BEAT_SCHEDULE = {
    # This task scrapes for new links every 2 hours.
    'scrape-babypips-for-links': {
        'task': 'forex_agent.tasks.scrape_babypips_for_links',
        'schedule': crontab(minute='*/10'),  # Runs at 00:00, 02:00, etc.
        # 'schedule': crontab(minute='0', hour='*/2'),  # Runs at 00:00, 02:00, etc.
    },
    # This task fetches news every 2 hours, offset from scraping.
    'fetch-market-news': {
        'task': 'forex_agent.tasks.fetch_and_process_market_news',
        'schedule': crontab(minute='*/7'), # Runs at 00:30, 02:30, etc.
        # 'schedule': crontab(minute='30', hour='*/2'), # Runs at 00:30, 02:30, etc.
    },
    # NEW: This task runs every 5 minutes to process one item from the raw content queue.
    'process-one-staged-content-item': {
        'task': 'forex_agent.tasks.process_one_staged_content_item',
        'schedule': crontab(minute='*/5'), # Runs every 5 minutes.
    },
    # This is the hard-coded schedule that avoids using the Admin panel.
    "keep-render-service-awake": {
        "task": "a2a_protocol.tasks.keep_service_awake",  # This must match the name in @shared_task
        "schedule": 60.0,  # Run every 60 seconds (1 minute) to keep service awake.
    },
}



# ==============================================================================
# TEMPLATES, INTERNATIONALIZATION, PASSWORDS
# ==============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]



# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i1n/

LANGUAGE_CODE = 'en-us'

# Consider 'Africa/Lagos' if that's your primary timezone for consistency with Celery
# TIME_ZONE = "Africa/Lagos"   # Can be 'Africa/Lagos' or 'UTC'
TIME_ZONE = 'UTC'


USE_I18N = True

USE_TZ = True



# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'



# ==============================================================================
# STATIC & MEDIA FILES CONFIGURATION
# ==============================================================================
STATIC_URL = 'static/'
# This is where `collectstatic` will gather all static files for production.
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# This storage engine handles compression and caching for you.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')





# ==============================================================================
# DJANGO REST FRAMEWORK & CUSTOM ERROR HANDLING
# ==============================================================================
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    # Register our custom exception handler to ensure all API errors
    # return a clean, consistent JSON response.
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
}


# ==============================================================================
# ROBUST LOGGING CONFIGURATION (CONSOLE-ONLY)
# ==============================================================================
# This simplified configuration sends all logs to the console (stdout) for
# both development and production. This is the industry standard for cloud
# platforms like Leapcell, as they capture the stdout stream for logging.
# It completely removes file-based logging to prevent filesystem errors.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module} [{process:d}:{thread:d}] - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',  # Capture all log levels from DEBUG upwards.
            'class': 'logging.StreamHandler',
            'formatter': 'verbose', # Use the more detailed formatter.
            'stream': sys.stdout,
        },
    },
    'loggers': {
        # Root logger: Catches logs from all other libraries.
        # Set to INFO to reduce noise from third-party packages.
        '': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        # Django's own loggers: Capture important framework messages.
        'django': {
            'handlers': ['console'],
            'level': 'INFO', # Use INFO for Django to avoid excessive noise.
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING', # Only show database logs if there's a problem.
            'propagate': False,
        },
        # Our application's loggers: Set to DEBUG to get all our messages.
        'forex_agent': {
            'handlers': ['console'],
            'level': 'DEBUG', # Capture all our custom logs
            'propagate': False,
        },
        'a2a_protocol': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        # core/settings.py -> LOGGING['loggers']
        'direct_agent': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# ==============================================================================
# CUSTOM APPLICATION CONFIGURATION
# ==============================================================================
# This is where we will store the configuration for our web scraper.
SCRAPER_CONFIG = {
    "BABYPIPS": {
        "START_URL": "https://www.babypips.com/learn/forex",
        "BASE_URL": "https://www.babypips.com",
        "LINK_SELECTOR": "a[href^='/learn/forex/']",
        "TITLE_SELECTOR": "h1",
        "CONTENT_SELECTOR": "article",
        "RESPECTFUL_LIMIT": 10,  # Max number of new pages to scrape per run
    }
}