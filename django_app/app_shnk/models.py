from django.db import models


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
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib raqami")  # ✅ Tartib

    class Meta:
        db_table = "sren"
        verbose_name = "SREN"
        verbose_name_plural = "SREN"

class  SREN_SHNQ(models.Model):
    sren = models.ForeignKey(SREN, on_delete=models.CASCADE)
    name = models.CharField(max_length=500, verbose_name="Nomi", db_index=True)
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
            models.Index(fields=["subsystem"]),  
        ]

    def __str__(self):
        return self.title
    
class ShnkInformation(models.Model):
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