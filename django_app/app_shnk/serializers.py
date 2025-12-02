from rest_framework import serializers
from .models import Texnik_reglaament, Standard

class TexnikReglaamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Texnik_reglaament
        fields = ["id", "name_uz", "name_ru", "pdf_uz", "pdf_ru"]


class StandardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Standard
        fields = '__all__'