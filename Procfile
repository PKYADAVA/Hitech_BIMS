web: python manage.py migrate --noinput && gunicorn --config gunicorn.conf.py --bind 0.0.0.0:$PORT Hitech_BIMS.wsgi:application
