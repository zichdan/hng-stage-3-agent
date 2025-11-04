# utilities/tasks.py
import requests
import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task(name="keep_service_awake")
def keep_service_awake():
    """
    A periodic Celery task that sends a request to the site's own URL
    to prevent the Render free tier service from spinning down.
    """
    site_url = getattr(settings, 'SITE_URL', None)

    if not site_url:
        logger.warning("SITE_URL setting is not configured. Cannot run keep_service_awake task.")
        return

    try:
        response = requests.get(site_url, timeout=15)
        if response.status_code == 200:
            logger.info(f"Successfully pinged {site_url} to keep service awake.")
        else:
            logger.error(f"Failed to ping {site_url}. Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while pinging {site_url}: {e}")