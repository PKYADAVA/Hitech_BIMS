from django.urls import path
from . import views

urlpatterns = [
    path("picklists/", views.picklists, name="picklists"),
    path("picklists/api/", views.PicklistAPI.as_view(), name="picklist_list"),
    path("picklists/api/create/", views.PicklistAPI.as_view(), name="picklist_create"),
    path("picklists/api/<int:id>/", views.PicklistAPI.as_view(), name="picklist_update"),
    path("picklists/api/<int:id>/delete/", views.PicklistAPI.as_view(), name="picklist_delete"),
    path("picklists/source-options/", views.source_options, name="picklist_source_options"),

    path("picklists/<int:picklist_id>/values/", views.PicklistValueAPI.as_view(), name="picklist_value_list"),
    path("picklists/<int:picklist_id>/values/create/", views.PicklistValueAPI.as_view(), name="picklist_value_create"),
    path("picklists/<int:picklist_id>/values/<int:id>/", views.PicklistValueAPI.as_view(), name="picklist_value_update"),
    path("picklists/<int:picklist_id>/values/<int:id>/delete/", views.PicklistValueAPI.as_view(), name="picklist_value_delete"),

    path("field_bindings/", views.field_bindings, name="field_bindings"),
    path("field_bindings/api/", views.FieldPicklistBindingAPI.as_view(), name="field_binding_list"),
    path("field_bindings/api/create/", views.FieldPicklistBindingAPI.as_view(), name="field_binding_create"),
    path("field_bindings/api/<int:id>/", views.FieldPicklistBindingAPI.as_view(), name="field_binding_update"),
    path("field_bindings/api/<int:id>/delete/", views.FieldPicklistBindingAPI.as_view(), name="field_binding_delete"),
]
