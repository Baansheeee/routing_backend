#!/usr/bin/env bash
# Render build command: bash build.sh
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
