#!/usr/bin/env bash
#
# Idempotent deployment script for Hitech BIMS. Runs on the droplet, inside
# the project directory. Pulls the latest main, installs dependencies,
# migrates the database, collects static files, and restarts services.
#
# On failure after the code has already moved, it rolls back to the commit
# that was deployed before this run started.
#
# Usage: ./deploy.sh

set -euo pipefail

PROJECT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${VENV_PATH:-$PROJECT_PATH/hitech_env}"
BRANCH="${DEPLOY_BRANCH:-main}"
LOG_PREFIX="[deploy]"

log() {
    echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') $*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

cd "$PROJECT_PATH"

[ -f "$PROJECT_PATH/.env" ] || fail ".env not found at $PROJECT_PATH/.env - refusing to deploy without it."
[ -d "$VENV_PATH" ] || fail "Virtualenv not found at $VENV_PATH."

PREVIOUS_COMMIT="$(git rev-parse HEAD)"
log "Current commit before deploy: $PREVIOUS_COMMIT"

rollback() {
    log "Deploy failed - rolling back to $PREVIOUS_COMMIT"
    git reset --hard "$PREVIOUS_COMMIT"
    # shellcheck source=/dev/null
    source "$VENV_PATH/bin/activate"
    pip install --quiet -r requirements.txt
    sudo systemctl restart gunicorn || true
    log "Rollback complete. Service restarted on previous commit."
}
trap 'rollback' ERR

log "Fetching latest changes on $BRANCH"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
NEW_COMMIT="$(git rev-parse HEAD)"
log "Deploying commit: $NEW_COMMIT"

# shellcheck source=/dev/null
source "$VENV_PATH/bin/activate"

log "Installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

log "Running Django system checks"
python manage.py check --deploy

log "Applying database migrations"
python manage.py migrate --noinput

log "Collecting static files"
python manage.py collectstatic --noinput

log "Restarting gunicorn"
sudo systemctl restart gunicorn
sudo systemctl is-active --quiet gunicorn || fail "gunicorn failed to start after restart."

log "Reloading nginx"
sudo nginx -t
sudo systemctl reload nginx

trap - ERR
log "Deploy complete: $PREVIOUS_COMMIT -> $NEW_COMMIT"
