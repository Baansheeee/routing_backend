"""URL routes for the routing API."""

from django.urls import path

from routing.views import AnalyzeView, GeocodeSuggestView, HealthView, HeatmapView

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("geocode/suggest", GeocodeSuggestView.as_view(), name="geocode-suggest"),
    path("analyze", AnalyzeView.as_view(), name="analyze"),
    path("heatmap", HeatmapView.as_view(), name="heatmap"),
]
