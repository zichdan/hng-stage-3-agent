#!/usr/bin/env bash
# Exit on error
set -o errexit

# --- Poetry Installation (Recommended for Dependency Management) ---
# If you are using requirements.txt, you can stick with pip.
# However, Poetry provides better dependency locking and management for production.
# pip install poetry
# poetry config virtualenvs.create false
# poetry install --no-root --no-dev

# --- Pip Installation (Current Method) ---
echo "Installing Python dependencies..."
pip install -r requirements.txt

# --- Django Management Commands ---
echo "Running Django management commands..."
# Run collectstatic to gather all static files for serving.
python manage.py collectstatic --noinput --clear
# Apply any pending database migrations.
python manage.py migrate --noinput

echo "Build script finished successfully."

# pip install -r requirements.txt && python manage.py collectstatic --no-input --clear && python manage.py migrate