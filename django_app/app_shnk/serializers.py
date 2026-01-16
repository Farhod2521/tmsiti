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
    

class ShnkInformationCreateSerializer(serializers.ModelSerializer):
    name_uz = serializers.CharField(required=False)
    name_ru = serializers.CharField(required=False)
    designation = serializers.CharField(required=True)
    change = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    order = serializers.IntegerField(required=False, default=0)
    
    class Meta:
        model = ShnkInformation
        fields = [
            'name_uz',
            'name_ru',
            'designation',
            'change',
            'order'
        ]

class ShnkGroupInformationCreateSerializer(serializers.ModelSerializer):
    title_uz = serializers.CharField(required=False)
    title_ru = serializers.CharField(required=False)
    shnk_information = ShnkInformationCreateSerializer(many=True, required=False)
    
    class Meta:
        model = ShnkGroupInformation
        fields = [
            'title_uz',
            'title_ru',
            'shnk_information'
        ]

class BulkShnkUploadSerializer(serializers.Serializer):
    shnk_groups = ShnkGroupInformationCreateSerializer(many=True)