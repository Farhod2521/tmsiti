from django.contrib import admin
from .models import Subsystem, ShnkGroup, Shnk
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
    list_display = ("name", "designation", "shnkgroup")
    search_fields = ("name", "designation")
    list_filter = ("shnkgroup",)
