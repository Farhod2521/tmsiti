from rest_framework import serializers
from .models import Texnik_reglaament

class TexnikReglaamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Texnik_reglaament
        fields = ["id", "name_uz", "name_ru", "pdf_uz", "pdf_ru"]
