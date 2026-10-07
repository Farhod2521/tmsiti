from django.contrib import admin, messages
from .models import Subsystem, ShnkGroup, Shnk, Qurilish_reglaament, Malumotnoma, SREN, SREN_SHNQ, Texnik_reglaament, Standard, ShnkGroupInformation, ShnkInformation, ShnkEdition
from .shnq_docs import process_edition, rebuild_chain, resolve_lang
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
    list_display = ("id","order","name", "designation", "status", "pdf_uz","pdf_ru","url","shnkgroup")
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
class CustomerAdmin(ImportExportModelAdmin):
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



@admin.register(ShnkEdition)
class ShnkEditionAdmin(admin.ModelAdmin):
    """Django admin orqali ham .docx yuklash mumkin — saqlanganda matn avtomatik ajratiladi."""
    list_display = ("id", "shnk", "lang", "edition_date", "note", "blocks_count", "parse_error")
    list_filter = ("lang",)
    search_fields = ("shnk__designation", "shnk__name_uz", "note")
    autocomplete_fields = ("shnk",)
    fields = ("shnk", "lang", "edition_date", "note", "source_file", "parse_error")
    readonly_fields = ("parse_error",)

    @admin.display(description="Bloklar")
    def blocks_count(self, obj):
        return (obj.stats or {}).get("blocks", 0)

    def save_model(self, request, obj, form, change):
        old = ShnkEdition.objects.filter(pk=obj.pk).values("shnk_id", "lang").first() if change else None
        super().save_model(request, obj, form, change)
        if not change or "source_file" in form.changed_data:
            try:
                raw = process_edition(obj)
                obj.lang = resolve_lang(obj.lang, raw)
                obj.save(update_fields=["lang"])
            except ValueError as exc:
                obj.parse_error = str(exc)
                obj.save(update_fields=["parse_error"])
                messages.error(request, f"Faylni o'qib bo'lmadi: {exc}")
        rebuild_chain(obj.shnk_id, obj.lang)
        if old and (old["shnk_id"], old["lang"]) != (obj.shnk_id, obj.lang):
            rebuild_chain(old["shnk_id"], old["lang"])

    def delete_model(self, request, obj):
        shnk_id, lang = obj.shnk_id, obj.lang
        obj.source_file.delete(save=False)
        super().delete_model(request, obj)
        rebuild_chain(shnk_id, lang)

    def delete_queryset(self, request, queryset):
        chains = set(queryset.values_list("shnk_id", "lang"))
        for obj in queryset:
            obj.source_file.delete(save=False)
        super().delete_queryset(request, queryset)
        for shnk_id, lang in chains:
            rebuild_chain(shnk_id, lang)


@admin.register(ShnkGroupInformation)
class ShnkGroupInformationAdmin(TranslationAdmin):
    list_display = ('id', 'title')
    search_fields = ('title',)
    ordering = ('id',)


@admin.register(ShnkInformation)
class ShnkInformationAdmin(TranslationAdmin):
    list_display = (
        'id',
        'name',
        'designation',
        'order',
        'status',
    )
    list_filter = ('status',)
    search_fields = ('name', 'designation')
    ordering = ('order',)

    fieldsets = (
        ("Asosiy maʼlumotlar", {
            'fields': (
                'shnkgroup',
                'name_uz',
                'name_ru',
                'designation',
                'change',
            )
        }),
        ("Fayllar", {
            'fields': (
                'pdf_uz',
                'pdf_ru',
                'url',
            )
        }),
        ("Sozlamalar", {
            'fields': (
                'order',
                'status',
            )
        }),
    )