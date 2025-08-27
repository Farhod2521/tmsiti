
from django.urls import path
from .views import TexnikReglaamentListAPIView

urlpatterns = [
    path("texnik-reglament/", TexnikReglaamentListAPIView.as_view(), name="texnik-reglament-list"),
]
