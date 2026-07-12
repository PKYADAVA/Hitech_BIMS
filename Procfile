web: python manage.py migrate --noinput && (python manage.py seed_sms_templates || true) && gunicorn --config gunicorn.conf.py --bind 0.0.0.0:$PORT Hitech_BIMS.wsgi:application
