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
    DeliveryChallanListTemplateView,
    DeliveryChallanFormTemplateView,
    DeliveryChallanAPI,
    TraySetListTemplateView,
    TraySetFormTemplateView,
    TraySettingAPI,
    HatchEntryListTemplateView,
    HatchEntryFormTemplateView,
    HatchEntryAPI,
    ChickSaleListTemplateView,
    ChickSaleFormTemplateView,
    ChickSaleAPI,
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

    path('tray-set/', TraySetListTemplateView.as_view(), name='tray_set_list'),
    path('tray-set/add/', TraySetFormTemplateView.as_view(), name='tray_set_add'),
    path('tray-set/<int:id>/edit/', TraySetFormTemplateView.as_view(), name='tray_set_edit'),
    path('tray_set_api/', TraySettingAPI.as_view(), name='tray_set_api_list'),
    path('tray_set_api/<int:id>/', TraySettingAPI.as_view(), name='tray_set_api_detail'),

    path('hatch-entry/', HatchEntryListTemplateView.as_view(), name='hatch_entry_list'),
    path('hatch-entry/add/', HatchEntryFormTemplateView.as_view(), name='hatch_entry_add'),
    path('hatch-entry/<int:id>/edit/', HatchEntryFormTemplateView.as_view(), name='hatch_entry_edit'),
    path('hatch_entry_api/', HatchEntryAPI.as_view(), name='hatch_entry_api_list'),
    path('hatch_entry_api/<int:id>/', HatchEntryAPI.as_view(), name='hatch_entry_api_detail'),

    path('chick-sale/', ChickSaleListTemplateView.as_view(), name='chick_sale_list'),
    path('chick-sale/add/', ChickSaleFormTemplateView.as_view(), name='chick_sale_add'),
    path('chick-sale/<int:id>/edit/', ChickSaleFormTemplateView.as_view(), name='chick_sale_edit'),
    path('chick_sale_api/', ChickSaleAPI.as_view(), name='chick_sale_api_list'),
    path('chick_sale_api/<int:id>/', ChickSaleAPI.as_view(), name='chick_sale_api_detail'),

    path('delivery-challan/', DeliveryChallanListTemplateView.as_view(), name='delivery_challan_list'),
    path('delivery-challan/add/', DeliveryChallanFormTemplateView.as_view(), name='delivery_challan_add'),
    path('delivery-challan/<int:id>/edit/', DeliveryChallanFormTemplateView.as_view(), name='delivery_challan_edit'),
    path('delivery_challan_api/', DeliveryChallanAPI.as_view(), name='delivery_challan_api_list'),
    path('delivery_challan_api/<int:id>/', DeliveryChallanAPI.as_view(), name='delivery_challan_api_detail'),
]
