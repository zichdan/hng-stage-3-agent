#!/usr/bin/env bash

# ==============================================================================
# ULTIMATE PRODUCTION STARTUP SCRIPT
# ==============================================================================
# This script robustly starts Gunicorn, a Celery worker, and Celery Beat.
# It is designed for stability and performance in a containerized environment.

# Exit immediately if any command fails.
set -o errexit

echo "--- Preparing and Starting Application Processes ---"

# --- 1. Start the Gunicorn Web Server ---
# This serves the Django API. It runs in the background (&).
# --workers: (2 * NUM_CORES) + 1 is a common formula. For a 2-core machine, 5 is a great start.
# --worker-class gevent: Uses gevent for asynchronous I/O, which is highly
#   efficient for apps that make many external API calls, just like ours.
# --timeout 120: A generous timeout for potentially slow AI responses.
echo "Starting Gunicorn web server with gevent workers..."
gunicorn core.wsgi:application \
    --bind 0.0.0.0:8080 \
    --workers 5 \
    --worker-class gevent \
    --threads 2 \
    --timeout 120 \
    --log-level info &

# --- 2. Start the Celery Worker ---
# This process handles our on-demand and scheduled AI tasks.
# -A core: Points to the Celery app instance in our 'core' project.
# --concurrency=4: Allows the worker to run up to 4 tasks in parallel.
# -P gevent: Uses the gevent pool, which is perfect for I/O-bound tasks like
#   API calls and database queries. It can handle thousands of concurrent
#   connections with very little memory overhead.
# --max-tasks-per-child=500: A critical stability feature. It forces a worker
#   process to restart after completing 500 tasks, preventing slow memory leaks.
echo "Starting Celery worker with gevent pool..."
celery -A core worker --loglevel=info --concurrency=4 -P gevent --max-tasks-per-child=500 &

# --- 3. Start the Celery Beat Scheduler ---
# This process triggers our periodic tasks (e.g., scraping, news fetching).
# --scheduler: Uses the Django database as the persistent storage for the schedule.
# This ensures that even if the server restarts, it knows what it was supposed to do.
echo "Starting Celery Beat scheduler..."
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler &

# --- Keep the Script Alive ---
# `wait -n` waits for any of the background processes to exit. If one crashes,
# this script will exit, causing the container orchestrator (like Docker or Leapcell)
# to restart the whole service, providing a self-healing mechanism.
echo "--- All processes are running. Monitoring for failures. ---"
wait -n

# Exit with the status of the process that exited first.
exit $?