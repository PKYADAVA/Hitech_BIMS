import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hitech_BIMS.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.filter(username='admin').delete()
user = User(username='admin', email='admin@example.com', is_staff=True, is_superuser=True)
user.set_password('admin12345')
user.save()
print('superuser created')
