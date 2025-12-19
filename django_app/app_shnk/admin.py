from django.contrib import admin
from .models import Subsystem, ShnkGroup, Shnk, Qurilish_reglaament, Malumotnoma, SREN, SREN_SHNQ, Texnik_reglaament, Standard
from modeltranslation.admin import TranslationAdmin, TabbedTranslationAdmin
from import_export.admin import  ImportExportModelAdmin


from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

User = get_user_model()

# Agar oldin register bo‘lgan bo‘lsa — o‘chirib yuboramiz
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # Faqat displaylar kerak bo‘lsa qo‘shish mumkin
    list_display = ("id",  "is_staff", "is_superuser")


    # Username olib tashlanganligi uchun kerak

    ordering = ("id",)

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
    list_display = ("id","order","name", "designation","pdf_uz","pdf_ru","url","shnkgroup")
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
class StandardAdmin(TranslationAdmin):
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



# admin.py

from .models import Quiz, Customer


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("id", "status")
    list_filter = ("status",)
    search_fields = ("id",)
    ordering = ("-id",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "phone",
        "email",
        "corrent_ans",
        "create_date",
    )
    list_filter = ("create_date",)
    search_fields = ("full_name", "phone", "email")
    ordering = ("-create_date",)

    readonly_fields = ("create_date",)
