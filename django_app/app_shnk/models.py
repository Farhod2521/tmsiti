from django.db import models
from django.db.models import F

class Subsystem(models.Model):
    title = models.CharField(max_length=500, verbose_name="Quyi tizim", db_index=True)

    class Meta:
        db_table = "subsystems"
        verbose_name = "Quyi tizim"
        verbose_name_plural = "Quyi tizimlar"

    def __str__(self):
        return self.title
    

class ShnkGroup(models.Model): 
    subsystem = models.ForeignKey(Subsystem, on_delete=models.CASCADE, db_index=True)
    title = models.CharField(max_length=500, verbose_name="Guruhlar", db_index=True)

    class Meta:
        db_table = "shnk_groups"
        verbose_name = "Guruh"
        verbose_name_plural = "Guruhlar"
        indexes = [
            models.Index(fields=["title"]),  
            models.Index(fields=["subsystem"]),  
        ]

    def __str__(self):
        return self.title
    
class Shnk(models.Model):
    shnkgroup = models.ForeignKey(ShnkGroup, on_delete=models.CASCADE, db_index=True)
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    designation = models.CharField(max_length=100, verbose_name="Belgilanishi", db_index=True)
    change = models.CharField(max_length=100, verbose_name="O'zgargani",blank=True, null=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    url = models.CharField(max_length=500, verbose_name="Url", blank=True, null=True)
    order =  models.PositiveIntegerField(default=0)
    status =  models.BooleanField(default=True)

    class Meta:
        db_table = "shnks"
        verbose_name = "SHNK"
        verbose_name_plural = "SHNKlar"
        indexes = [
            models.Index(fields=["name"]),  
            models.Index(fields=["designation"]),  
        ]
    def save(self, *args, **kwargs):
        # yangi obyektmi yoki yangilanayotganmi — tekshiramiz
        is_new = self.pk is None

        if is_new:
            # Agar yangi qo‘shilayotgan bo‘lsa
            Shnk.objects.filter(order__gte=self.order).update(order=models.F("order") + 1)
        else:
            # Eski obyekt o‘zgartirilsa
            old_order = Shnk.objects.get(pk=self.pk).order

            # Agar yangi order eski orderdan kichik bo‘lsa → pastdagilarni ko‘taramiz
            if self.order < old_order:
                Shnk.objects.filter(
                    order__gte=self.order,
                    order__lt=old_order
                ).update(order=models.F("order") + 1)

            # Agar yangi order eski orderdan katta bo‘lsa → yuqoridagilarni kamaytiramiz
            elif self.order > old_order:
                Shnk.objects.filter(
                    order__lte=self.order,
                    order__gt=old_order
                ).update(order=models.F("order") - 1)

        super().save(*args, **kwargs)
    def __str__(self):
        return self.name


def shnq_edition_upload_to(instance, filename):
    # Nomi o'zgartirilmaydi: eski migratsiyalar shu funksiyaga ishora qiladi
    return f"FILES/shnq_editions/{instance.media_folder()}/{filename}"


class DocEditionBase(models.Model):
    """
    Hujjatning bitta tahriri (lex.uz dagi kabi): fayl -> bloklar -> oldingi tahrir bilan solishtirish.
    SHNQ (ShnkEdition) va qonunlar (LawEdition) uchun umumiy.
    """
    LANG_CHOICES = (("uz", "O'zbekcha (lotin)"), ("kr", "Ўзбекча (кирилл)"), ("ru", "Русский"))
    SOURCE_CHOICES = (("manual", "Qo'lda yuklangan"), ("lex", "lex.uz dan avtomatik"))
    OWNER_FIELD = None  # "shnk_id" / "law_id"

    lang = models.CharField(max_length=2, choices=LANG_CHOICES, default="uz", verbose_name="Til")
    source_file = models.FileField(upload_to=shnq_edition_upload_to, verbose_name="Fayl (lex.uz .doc yoki Word .docx)")
    edition_date = models.DateField(verbose_name="Tahrir sanasi")
    note = models.CharField(
        max_length=1000, blank=True, default="",
        verbose_name="O'zgartirish kiritgan hujjat",
        help_text="Masalan: Qurilish vazirining 2025-yil 24-iyundagi 01/2-37-son buyrug'i (hisob raqami 358)",
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual", verbose_name="Manba")
    content_hash = models.CharField(max_length=40, blank=True, default="", editable=False)
    raw_blocks = models.JSONField(default=list, blank=True, editable=False)
    blocks = models.JSONField(default=list, blank=True, editable=False)
    toc = models.JSONField(default=list, blank=True, editable=False)
    stats = models.JSONField(default=dict, blank=True, editable=False)
    parse_error = models.TextField(blank=True, default="", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def owner_id(self):
        return getattr(self, self.OWNER_FIELD)

    def media_folder(self):
        raise NotImplementedError


class ShnkEdition(DocEditionBase):
    OWNER_FIELD = "shnk_id"

    shnk = models.ForeignKey(Shnk, on_delete=models.CASCADE, related_name="editions", verbose_name="SHNQ")

    class Meta:
        db_table = "shnq_editions"
        verbose_name = "SHNQ tahriri"
        verbose_name_plural = "SHNQ tahrirlari (matn)"
        ordering = ["shnk", "lang", "edition_date", "id"]

    def media_folder(self):
        return str(self.shnk_id)

    def __str__(self):
        return f"{self.shnk.designation} [{self.lang}] {self.edition_date}"


class LawDocument(models.Model):
    """
    Qonunlar bo'limi: SHNQ matnlarida havola qilingan lex.uz hujjatlari (kodeks, qonun, qaror...).
    lex.uz dan avtomatik yuklanadi, havola bosilganda sayt ichida ochiladi.
    """
    title_uz = models.CharField(max_length=1000, blank=True, default="", verbose_name="Nomi (lotin)")
    title_kr = models.CharField(max_length=1000, blank=True, default="", verbose_name="Nomi (кирилл)")
    title_ru = models.CharField(max_length=1000, blank=True, default="", verbose_name="Nomi (рус)")
    number = models.CharField(max_length=200, blank=True, default="", verbose_name="Raqami")
    doc_date = models.DateField(null=True, blank=True, verbose_name="Qabul qilingan sana")
    status = models.BooleanField(default=True, verbose_name="Amalda")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "law_documents"
        verbose_name = "Qonun hujjati"
        verbose_name_plural = "Qonunlar"
        ordering = ["-doc_date", "id"]

    @property
    def title(self):
        return self.title_kr or self.title_uz or self.title_ru

    def __str__(self):
        return self.title[:120] or f"#{self.pk}"


class LawEdition(DocEditionBase):
    OWNER_FIELD = "law_id"

    law = models.ForeignKey(LawDocument, on_delete=models.CASCADE, related_name="editions", verbose_name="Qonun")

    class Meta:
        db_table = "law_editions"
        verbose_name = "Qonun tahriri"
        verbose_name_plural = "Qonun tahrirlari"
        ordering = ["law", "lang", "edition_date", "id"]

    def media_folder(self):
        return f"law_{self.law_id}"

    def __str__(self):
        return f"{self.law} [{self.lang}] {self.edition_date}"


class LexSource(models.Model):
    """lex.uz bilan bog'lanish: hujjatning har bir tildagi lex raqami va oxirgi import holati."""
    STATUS_CHOICES = (
        ("pending", "Kutilmoqda"),
        ("ok", "Yuklangan"),
        ("stub", "Matn yo'q (PDF qoladi)"),
        ("mismatch", "Shifr mos emas"),
        ("error", "Xato"),
    )

    shnk = models.OneToOneField(Shnk, on_delete=models.CASCADE, null=True, blank=True, related_name="lex_source")
    law = models.OneToOneField(LawDocument, on_delete=models.CASCADE, null=True, blank=True, related_name="lex_source")
    lex_ids = models.JSONField(default=dict, blank=True, verbose_name="lex.uz raqamlari")  # {"kr": 1, "uz": -1, "ru": 2}
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    message = models.TextField(blank=True, default="")
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lex_sources"
        verbose_name = "lex.uz manbasi"
        verbose_name_plural = "lex.uz manbalari"

    def __str__(self):
        return f"{self.shnk or self.law} {self.lex_ids}"


class LexSyncJob(models.Model):
    """lex.uz dan avtomatik import jarayoni (admin paneldan kuzatiladi)."""
    STATUS_CHOICES = (
        ("queued", "Navbatda"),
        ("running", "Ishlamoqda"),
        ("done", "Tugadi"),
        ("stopped", "To'xtatildi"),
        ("failed", "Xato bilan tugadi"),
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="queued")
    params = models.JSONField(default=dict, blank=True)
    total = models.PositiveIntegerField(default=0)
    done = models.PositiveIntegerField(default=0)
    counters = models.JSONField(default=dict, blank=True)
    current = models.CharField(max_length=500, blank=True, default="")
    log = models.TextField(blank=True, default="")
    stop_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lex_sync_jobs"
        verbose_name = "lex.uz import jarayoni"
        verbose_name_plural = "lex.uz import jarayonlari"
        ordering = ["-id"]


class ShnkCounter(models.Model):
    shnk = models.OneToOneField(Shnk, on_delete=models.CASCADE, related_name="counter")
    views = models.PositiveIntegerField(default=0)
    downloads = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "shnq_counters"
        verbose_name = "SHNQ statistikasi"
        verbose_name_plural = "SHNQ statistikasi"


class Qurilish_reglaament(models.Model):
    group    =  models.CharField(max_length=500, verbose_name="Guruhi")
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    designation = models.CharField(max_length=100, verbose_name="Belgilanishi", db_index=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)

    class Meta:
        db_table = "qurilish_reglaament"
        verbose_name = "Qurilish_reglaament"
        verbose_name_plural = "Qurilish_reglaament"


class Malumotnoma(models.Model):
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    designation = models.CharField(max_length=100, verbose_name="Belgilanishi", db_index=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)

    class Meta:
        db_table = "Malumotnoma"
        verbose_name = "Malumotnoma"
        verbose_name_plural = "Malumotnoma"

class Metodik_Qolanma(models.Model):
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    pdf_uz = models.FileField(upload_to="FILES/Metodik_Qolanma", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/Metodik_Qolanma", blank=True, null=True)

    class Meta:
        db_table = "metodik_qolanma"
        verbose_name = "Metodik_Qolanma"
        verbose_name_plural = "Metodik_Qolanma"




class SREN(models.Model):
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    designation = models.CharField(max_length=100, verbose_name="Belgilanishi", db_index=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib raqami")

    class Meta:
        db_table = "sren"
        verbose_name = "SREN"
        verbose_name_plural = "SREN"
        ordering = ["order"]  # ✅ adminda tartib bilan chiqadi

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            # yangi qo‘shilganda joy ochamiz
            SREN.objects.filter(order__gte=self.order).update(order=F("order") + 1)
        else:
            old_order = SREN.objects.get(pk=self.pk).order

            if self.order < old_order:
                SREN.objects.filter(
                    order__gte=self.order,
                    order__lt=old_order
                ).exclude(pk=self.pk).update(order=F("order") + 1)

            elif self.order > old_order:
                SREN.objects.filter(
                    order__lte=self.order,
                    order__gt=old_order
                ).exclude(pk=self.pk).update(order=F("order") - 1)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class  SREN_SHNQ(models.Model):
    sren = models.ForeignKey(SREN, on_delete=models.CASCADE)
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    designation = models.CharField(max_length=100, verbose_name="Belgilanishi", db_index=True)
    class Meta:
        db_table = "sren_shnk"
        verbose_name = "SREN_SHNKQ"
        verbose_name_plural = "SREN_SHNKQ"



class Texnik_reglaament(models.Model):
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)

    class Meta:
        db_table = "Texnik_reglaament"
        verbose_name = "Texnik_reglaament"
        verbose_name_plural = "Texnik_reglaament"



import re
from django.utils.text import slugify

class Standard(models.Model):
    title = models.CharField(max_length=512, verbose_name="Sarlavha (default)")
    designation = models.CharField(max_length=255, verbose_name="Belgilanish (default)")
    pdf = models.FileField(upload_to="FILES/STANDARTLAR")
    slug = models.CharField(max_length=100, unique=True, verbose_name="Slug")
    number = models.PositiveIntegerField(verbose_name="Raqam")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqti")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="O'zgartirilgan vaqti")

    def save(self, *args, **kwargs):
        # 1) designation ichidagi kirill va maxsus belgilarni ASCII ga o‘tkazamiz
        clean = (
            self.designation
                .replace("O‘", "Oz").replace("o‘", "oz")
                .replace("Oʻ", "Oz").replace("oʻ", "oz")
                .replace("Ў", "O").replace("ў", "o")
                .replace("М", "M").replace("м", "m")
                .replace("С", "S").replace("с", "s")
                .replace("Т", "T").replace("т", "t")
        )

        # 2) faqat harf va raqamlarni qoldiramiz
        clean = re.sub(r'[^A-Za-z0-9]', '', clean)

        # 3) slug sifatida saqlaymiz (kichik qilib)
        self.slug = clean.lower()

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Standart hujjat"
        verbose_name_plural = "Standart hujjatlar"
        ordering = ["-number"]





class Quiz(models.Model):
    json =  models.JSONField()
    status  =  models.BooleanField(default=True)


class  Customer(models.Model):
    full_name = models.CharField(max_length=500, blank=True, null=True)
    phone =  models.CharField(max_length=20, blank=True, null=True)
    email =  models.CharField(max_length=200, blank=True, null=True)
    corrent_ans =  models.PositiveIntegerField(blank=True, null=True)
    result =  models.TextField(blank=True, null=True)
    create_date = models.DateTimeField(auto_now_add=True) 


    def __str__(self):
        return self.full_name
    




class ShnkGroupInformation(models.Model): 
    title = models.CharField(max_length=500, verbose_name="Guruhlar", db_index=True)

    class Meta:
        db_table = "shnk_groups_information"
        verbose_name = "Guruh Malumotnomalar"
        verbose_name_plural = "Guruhlar Malumotnomalar"
        indexes = [
            models.Index(fields=["title"]),  
        ]

    def __str__(self):
        return self.title
    
class ShnkInformation(models.Model):
    shnkgroup = models.ForeignKey(ShnkGroupInformation, on_delete=models.CASCADE, db_index=True)
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
    designation = models.CharField(max_length=100, verbose_name="Belgilanishi", db_index=True)
    change = models.CharField(max_length=100, verbose_name="O'zgargani",blank=True, null=True)
    pdf_uz = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    pdf_ru = models.FileField(upload_to="FILES/shnk", blank=True, null=True)
    url = models.CharField(max_length=500, verbose_name="Url", blank=True, null=True)
    order =  models.PositiveIntegerField(default=0)
    status =  models.BooleanField(default=True)

    class Meta:
        db_table = "shnks_information"
        verbose_name = "SHNK Malumotnomalar "
        verbose_name_plural = "SHNKlar Malumotnomalar"
        indexes = [
            models.Index(fields=["name"]),  
            models.Index(fields=["designation"]),  
        ]
    def save(self, *args, **kwargs):
        # yangi obyektmi yoki yangilanayotganmi — tekshiramiz
        is_new = self.pk is None

        if is_new:
            # Agar yangi qo‘shilayotgan bo‘lsa
            ShnkInformation.objects.filter(order__gte=self.order).update(order=models.F("order") + 1)
        else:
            # Eski obyekt o‘zgartirilsa
            old_order = ShnkInformation.objects.get(pk=self.pk).order

            # Agar yangi order eski orderdan kichik bo‘lsa → pastdagilarni ko‘taramiz
            if self.order < old_order:
                ShnkInformation.objects.filter(
                    order__gte=self.order,
                    order__lt=old_order
                ).update(order=models.F("order") + 1)

            # Agar yangi order eski orderdan katta bo‘lsa → yuqoridagilarni kamaytiramiz
            elif self.order > old_order:
                ShnkInformation.objects.filter(
                    order__lte=self.order,
                    order__gt=old_order
                ).update(order=models.F("order") - 1)

        super().save(*args, **kwargs)
    def __str__(self):
        return self.name