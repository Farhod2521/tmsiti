from django.contrib import admin
from .models import Subsystem, ShnkGroup, Shnk, Qurilish_reglaament
from modeltranslation.admin import TranslationAdmin
@admin.register(Subsystem)
class SubsystemAdmin(admin.ModelAdmin):
    list_display = ("title",)
    search_fields = ("title",)

@admin.register(ShnkGroup)
class ShnkGroupAdmin(admin.ModelAdmin):
    list_display = ("title", "subsystem")
    search_fields = ("title",)
    list_filter = ("subsystem",)

@admin.register(Shnk)
class ShnkAdmin(TranslationAdmin):
    list_display = ("id","name", "designation", "shnkgroup")
    search_fields = ("name", "designation")
    list_filter = ("shnkgroup",)



@admin.register(Qurilish_reglaament)
class Qurilish_reglaamentAdmin(TranslationAdmin):
    list_display = ("group","name", "designation",)
    search_fields = ("name", "designation")

