
from django.urls import path
from .views import TexnikReglaamentListAPIView, StandardPdfToImagesAPIView

urlpatterns = [
    path("texnik-reglament/", TexnikReglaamentListAPIView.as_view(), name="texnik-reglament-list"),
    path("standard/<slug:slug>/images/", StandardPdfToImagesAPIView.as_view())
]
