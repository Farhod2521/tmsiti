from django.contrib import admin
from .models import Subsystem, ShnkGroup, Shnk, Qurilish_reglaament, Malumotnoma
from modeltranslation.admin import TranslationAdmin
from import_export.admin import  ImportExportModelAdmin
@admin.register(Subsystem)
class SubsystemAdmin(TranslationAdmin):
    list_display = ("title_ru","title_uz",)
    search_fields = ("title",)

@admin.register(ShnkGroup)
class ShnkGroupAdmin(TranslationAdmin):
    list_display = ("title_ru","title_uz", "subsystem")
    search_fields = ("title",)
    list_filter = ("subsystem",)

@admin.register(Shnk)
class ShnkAdmin(TranslationAdmin):
    list_display = ("id","name", "designation", "shnkgroup")
    search_fields = ("name", "designation")
    list_filter = ("shnkgroup",)



@admin.register(Qurilish_reglaament)
class Qurilish_reglaamentAdmin(ImportExportModelAdmin,TranslationAdmin):
    list_display = ("group","name", "designation",)
    search_fields = ("name", "designation")

@admin.register(Malumotnoma)
class MalumotnomaAdmin(ImportExportModelAdmin,TranslationAdmin):
    list_display = ("name", "designation",)
    search_fields = ("name", "designation")