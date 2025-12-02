from django.contrib import admin
from .models import Subsystem, ShnkGroup, Shnk, Qurilish_reglaament, Malumotnoma, SREN, SREN_SHNQ, Texnik_reglaament, Standard
from modeltranslation.admin import TranslationAdmin, TabbedTranslationAdmin
from import_export.admin import  ImportExportModelAdmin


from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

User = get_user_model()

admin.site.register(User, UserAdmin)

@admin.register(Subsystem)
class SubsystemAdmin(TranslationAdmin):
    list_display = ("title",)
    search_fields = ("title",)

@admin.register(ShnkGroup)
class ShnkGroupAdmin(TranslationAdmin):
    list_display = ("title", "subsystem")
    search_fields = ("title",)
    list_filter = ("subsystem",)

@admin.register(Shnk)
class ShnkAdmin(TranslationAdmin):
    list_display = ("id","name", "designation","pdf_uz","pdf_ru","url","shnkgroup")
    search_fields = ("name", "designation")
    list_filter = ("shnkgroup",)



@admin.register(Qurilish_reglaament)
class Qurilish_reglaamentAdmin(ImportExportModelAdmin,TranslationAdmin):
    list_display = ("group","name", "designation",)
    search_fields = ("name", "designation")


@admin.register(Texnik_reglaament)
class Texnik_reglaamentAdmin(ImportExportModelAdmin,TranslationAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Malumotnoma)
class MalumotnomaAdmin(ImportExportModelAdmin,TranslationAdmin):
    list_display = ("name", "designation",)
    search_fields = ("name", "designation")


@admin.register(SREN)
class SRENAdmin(ImportExportModelAdmin, TranslationAdmin):
    list_display = ("name_uz","name_ru", "designation", "order")
    # list_editable = ("order","name_uz", "name_ru")
    search_fields = ("name", "designation")
@admin.register(SREN_SHNQ)
class SREN_SHNQAdmin(ImportExportModelAdmin,TranslationAdmin):
    list_display = ("name_uz","name_ru")
    # list_editable = ("name_uz", "name_ru")
    search_fields = ("name", "designation")



@admin.register(Standard)
class StandardAdmin(TabbedTranslationAdmin):
    list_display = ('id', 'designation', 'title', 'number', 'created_at')
    list_display_links = ('id', 'designation', 'title')
    search_fields = ('title', 'title_uz', 'title_ru', 'title_en',
                     'designation', 'designation_uz', 'designation_ru', 'designation_en')
    list_filter = ('created_at',)

    prepopulated_fields = {
        'slug': ('title',)
    }

    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ("Asosiy ma'lumotlar", {
            "fields": (
                "title",
                "designation",
                "slug",
                "number",
                "pdf",
            )
        }),
        ("Tizim ma'lumotlari", {
            "fields": (
                "created_at",
                "updated_at",
            )
        }),
    )