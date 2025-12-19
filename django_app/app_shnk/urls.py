
from django.urls import path
from .views import TexnikReglaamentListAPIView, StandardPdfToImagesAPIView, StandardListAPIView, QuizListAPIView, CustomerCreateAPIView

urlpatterns = [
    path("texnik-reglament/", TexnikReglaamentListAPIView.as_view(), name="texnik-reglament-list"),
    path("standard-list/", StandardListAPIView.as_view()),
    path("standard/<slug:slug>/images/", StandardPdfToImagesAPIView.as_view()), 
    path("quiz/list/", QuizListAPIView.as_view()),
    path("customer/create/", CustomerCreateAPIView.as_view()),
]
