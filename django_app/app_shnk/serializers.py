from rest_framework import serializers
from .models import Texnik_reglaament, Standard, ShnkGroupInformation, ShnkInformation

class TexnikReglaamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Texnik_reglaament
        fields = ["id", "name_uz", "name_ru", "pdf_uz", "pdf_ru"]


class StandardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Standard
        exclude = ["pdf", "title","designation" ]  # PDF qaytmasin!





class ShnkInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShnkInformation
        fields = (
            'id',
            'name_uz',
            'name_ru',
            'designation',
            'change',
            'pdf_uz',
            'pdf_ru',
            'url',
            'order',
        )

class ShnkGroupInformationSerializer(serializers.ModelSerializer):
    shnks = serializers.SerializerMethodField()

    class Meta:
        model = ShnkGroupInformation
        fields = (
            'id',
            'title_uz',
            'title_ru',
            'shnks',
        )

    def get_shnks(self, obj):
        queryset = ShnkInformation.objects.filter(
            shnkgroup=obj,
            status=True
        ).order_by('order')

        return ShnkInformationSerializer(queryset, many=True).data