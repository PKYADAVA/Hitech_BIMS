from django.urls import path
from .views import (
    HatchSettingListTemplateView,
    HatchSettingFormTemplateView,
    HatchSettingAPI,
    next_batch_flock_no,
    EggPurchaseListTemplateView,
    EggPurchaseFormTemplateView,
    EggPurchaseAPI,
    egg_purchase_next_number,
    EggGradingListTemplateView,
    EggGradingFormTemplateView,
    EggGradingAPI,
    egg_grading_next_number,
    egg_grading_stock_check,
    HatchReportView,
)

urlpatterns = [
    path('hatchery/', HatchSettingListTemplateView.as_view(), name='hatchery_list'),
    path('hatchery/add/', HatchSettingFormTemplateView.as_view(), name='hatchery_add'),
    path('hatchery/<int:id>/edit/', HatchSettingFormTemplateView.as_view(), name='hatchery_edit'),

    path('hatchery_api/', HatchSettingAPI.as_view(), name='hatchery_api_list'),
    path('hatchery_api/<int:id>/', HatchSettingAPI.as_view(), name='hatchery_api_detail'),
    path('hatchery/next-batch-flock-no/', next_batch_flock_no, name='next_batch_flock_no'),

    path('egg-purchase/', EggPurchaseListTemplateView.as_view(), name='egg_purchase_list'),
    path('egg-purchase/add/', EggPurchaseFormTemplateView.as_view(), name='egg_purchase_add'),
    path('egg-purchase/<int:id>/edit/', EggPurchaseFormTemplateView.as_view(), name='egg_purchase_edit'),
    path('egg-purchase/next-number/', egg_purchase_next_number, name='egg_purchase_next_number'),

    path('egg_purchase_api/', EggPurchaseAPI.as_view(), name='egg_purchase_api_list'),
    path('egg_purchase_api/<int:id>/', EggPurchaseAPI.as_view(), name='egg_purchase_api_detail'),

    path('egg-grading/', EggGradingListTemplateView.as_view(), name='egg_grading_list'),
    path('egg-grading/add/', EggGradingFormTemplateView.as_view(), name='egg_grading_add'),
    path('egg-grading/<int:id>/edit/', EggGradingFormTemplateView.as_view(), name='egg_grading_edit'),
    path('egg-grading/next-number/', egg_grading_next_number, name='egg_grading_next_number'),
    path('egg-grading/stock-check/', egg_grading_stock_check, name='egg_grading_stock_check'),

    path('egg_grading_api/', EggGradingAPI.as_view(), name='egg_grading_api_list'),
    path('egg_grading_api/<int:id>/', EggGradingAPI.as_view(), name='egg_grading_api_detail'),

    path('hatchery/report/', HatchReportView.as_view(), name='hatchery_report'),
]
