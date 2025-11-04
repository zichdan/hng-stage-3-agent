#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -o errexit

echo "Starting Gunicorn, Celery Worker, and Celery Beat..."

# Start Gunicorn web server in the background.
# --workers 1 is optimal for the free tier's shared CPU.
# --timeout 60 gives long requests more time to complete.
gunicorn core.wsgi:application --bind 0.0.0.0:${PORT} --workers 1 --threads 2 --timeout 60 --log-level info &

# Start Celery Worker in the background.
# --concurrency=1 is best for the free tier.
# --max-tasks-per-child=100 prevents memory leaks over time (critical for stability).
# --without-gossip --without-mingle makes it more lightweight.
celery -A core worker -l info --concurrency=1 --without-gossip --without-mingle --max-tasks-per-child=100 &

# Start Celery Beat scheduler in the background.
# --scheduler django_celery_beat... explicitly uses the database for schedules.
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler &

# Wait for any of the background processes to exit.
wait -n

# Exit with the status of the process that exited first.
exit $?














































# #!/usr/bin/env bash

# # ==============================================================================
# # PRODUCTION STARTUP SCRIPT FOR FOREX COMPASS AI AGENT
# # ==============================================================================
# # This script is designed to run Gunicorn (the web server), a Celery worker
# # (for on-demand AI tasks), and Celery Beat (for scheduled knowledge updates)
# # within a single container, which is ideal for free-tier deployments.
# # It uses background processes (&) to manage all three services concurrently.

# # Exit immediately if any command fails, ensuring a clean failure state.
# set -o errexit

# echo "--- Starting Application Processes ---"




# # --- 1. Start the Gunicorn Web Server ---
# # This serves the main Django application and the A2A API endpoint.
# # --bind: Binds to all network interfaces on the specified port.
# # --workers: Number of worker processes. For a free tier with 1 CPU, 3 is a good number.
# # --timeout: Sets a generous 120-second timeout for slow AI requests.
# # --log-level: Sets the logging level to 'info' for production.
# # The '&' at the end runs this process in the background.
# echo "Starting Gunicorn web server..."
# # gunicorn core.wsgi:application --bind 0.0.0.0:8080 --workers 3 --timeout 120 --log-level info &
# gunicorn core.wsgi:application --bind 0.0.0.0:8080 --workers 3 --threads 2 --timeout 120 --log-level info &









# # --- 2. Start the Celery Worker ---
# # This process listens to the Redis queue for on-demand tasks (e.g., process_user_query).
# # --concurrency: Number of parallel tasks. 2 is suitable for a free tier.
# # --loglevel: Sets the logging level.
# # --max-tasks-per-child: A critical setting for stability. It restarts a worker
# #   process after it has completed 100 tasks, preventing memory leaks over time.
# echo "Starting Celery worker..."
# celery -A core worker --loglevel=info --concurrency=4 -P gevent --max-tasks-per-child=100 &
# # celery -A core worker -l info --concurrency=4 -P gevent --max-tasks-per-child=100


# # --- 3. Start the Celery Beat Scheduler ---
# # This process is responsible for triggering our scheduled tasks (e.g., news fetching).
# # --scheduler: This tells Celery Beat to use the Django database to store its
# #   schedule, which is essential for persistence across restarts.
# echo "Starting Celery Beat scheduler..."
# celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler &

# # --- Keep the Script Alive ---
# # `wait -n` waits for any of the background processes to exit. If one of them
# # crashes, this script will also exit, causing the container to restart,
# # which provides a self-healing mechanism.
# echo "--- All processes started. Waiting for exit signal. ---"
# wait -n

# # Exit with the status of the process that exited first.
# exit $?









