
from django.urls import path
from .views import TexnikReglaamentListAPIView, StandardPdfToImagesAPIView, StandardListAPIView

urlpatterns = [
    path("texnik-reglament/", TexnikReglaamentListAPIView.as_view(), name="texnik-reglament-list"),
    path("standard-list/", StandardListAPIView.as_view()),
    path("standard/<slug:slug>/images/", StandardPdfToImagesAPIView.as_view())
]
