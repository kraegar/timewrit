from django.urls import path
from . import views, admin_views
from django.shortcuts import render

urlpatterns = [
    path('', views.index, name='index'),
    path('api/events/', views.events_json, name='events_json'),
    path('api/comments/', views.submit_comment, name='submit_comment'),
    path('api/people/<int:person_id>/', views.person_detail_json, name='person_detail_json'),
    path('api/locations/<int:location_id>/', views.location_detail_json, name='location_detail_json'),
    path('api/export-markdown/', views.export_markdown, name='export_markdown'),
    path('sources/', views.sources_library, name='sources_library'),
    path('admin/import/', admin_views.import_data, name='import_data'),
    path('admin/import-gedcom/', admin_views.gedcom_import_view, name='import_gedcom'),
    path('admin/cloning-guide/', admin_views.cloning_guide, name='cloning_guide'),
    path('admin/research-board/', admin_views.research_board_view, name='research_board'),
    path('test-vis/', lambda request: render(request, 'timeline/test_vis.html')),
    path('api/history/<str:model_name>/<int:obj_id>/', views.get_history, name='get_history'),
    path('api/network-graph/', views.network_graph_api, name='network_graph_api'),
    path('api/export-json/', views.export_json, name='export_json'),
    path('api/export-gedcom/', views.export_gedcom, name='export_gedcom'),
    path('api/export-pdf/', views.export_pdf, name='export_pdf'),
    path('api/global-search/', views.global_search_json, name='global_search_json'),
    path('help/', views.help_index, name='help_index'),
    path('help/<slug:slug>/', views.help_topic_detail, name='help_topic_detail'),
]
