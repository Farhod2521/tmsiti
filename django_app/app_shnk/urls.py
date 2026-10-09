
from django.urls import path
from . import shnq_views
from .views import TexnikReglaamentListAPIView, StandardPdfToImagesAPIView, StandardListAPIView, QuizListAPIView, CustomerCreateAPIView, ShnkGroupWithInformationAPIView, ShnkDataImportAPIView

urlpatterns = [
    path("texnik-reglament/", TexnikReglaamentListAPIView.as_view(), name="texnik-reglament-list"),
    path("standard-list/", StandardListAPIView.as_view()),
    path("standard/<slug:slug>/images/", StandardPdfToImagesAPIView.as_view()), 
    path("quiz/list/", QuizListAPIView.as_view()),
    path("customer/create/", CustomerCreateAPIView.as_view()),
    path('shnk-information/groups/', ShnkGroupWithInformationAPIView.as_view()),
    path('shnk-create/groups/', ShnkDataImportAPIView.as_view()),

    # SHNQ — lex.uz ko'rinishidagi matn va tahrirlar
    path("shnq/<int:pk>/", shnq_views.ShnqDocumentAPIView.as_view()),
    path("shnq/<int:pk>/download/", shnq_views.ShnqDownloadHitAPIView.as_view()),
    path("shnq-admin/login/", shnq_views.ShnqAdminLoginAPIView.as_view()),
    path("shnq-admin/documents/", shnq_views.ShnqAdminDocumentListAPIView.as_view()),
    path("shnq-admin/documents/<int:pk>/", shnq_views.ShnqAdminDocumentDetailAPIView.as_view()),
    path("shnq-admin/documents/<int:pk>/editions/", shnq_views.ShnqAdminEditionCreateAPIView.as_view()),
    path("shnq-admin/editions/<int:pk>/", shnq_views.ShnqAdminEditionAPIView.as_view()),
    path("shnq-admin/editions/<int:pk>/reparse/", shnq_views.ShnqAdminEditionReparseAPIView.as_view()),
    path("shnq-admin/lex-sync/", shnq_views.LexSyncStatusAPIView.as_view()),
    path("shnq-admin/lex-sync/start/", shnq_views.LexSyncStartAPIView.as_view()),
    path("shnq-admin/lex-sync/stop/", shnq_views.LexSyncStopAPIView.as_view()),

    # Qonunlar bo'limi (lex.uz dan avtomatik yuklangan)
    path("laws/", shnq_views.LawListAPIView.as_view()),
    path("laws/<int:pk>/", shnq_views.LawDocumentAPIView.as_view()),
]
