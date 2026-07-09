from django.urls import path
from .views import (
    HatchSettingListTemplateView,
    HatchSettingFormTemplateView,
    HatchSettingAPI,
)

urlpatterns = [
    path('hatchery/', HatchSettingListTemplateView.as_view(), name='hatchery_list'),
    path('hatchery/add/', HatchSettingFormTemplateView.as_view(), name='hatchery_add'),
    path('hatchery/<int:id>/edit/', HatchSettingFormTemplateView.as_view(), name='hatchery_edit'),

    path('hatchery_api/', HatchSettingAPI.as_view(), name='hatchery_api_list'),
    path('hatchery_api/<int:id>/', HatchSettingAPI.as_view(), name='hatchery_api_detail'),
]
