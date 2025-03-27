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

    class Meta:
        db_table = "shnks"
        verbose_name = "SHNK"
        verbose_name_plural = "SHNKlar"
        indexes = [
            models.Index(fields=["name"]),  
            models.Index(fields=["designation"]),  
        ]

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