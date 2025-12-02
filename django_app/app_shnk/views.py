from django.shortcuts import render

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Texnik_reglaament, Standard
from .serializers import TexnikReglaamentSerializer


import base64
from io import BytesIO
from pdf2image import convert_from_path

class TexnikReglaamentListAPIView(APIView):
    def get(self, request, *args, **kwargs):
        queryset = Texnik_reglaament.objects.all()
        serializer = TexnikReglaamentSerializer(queryset, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class StandardPdfToImagesAPIView(APIView):
    """
    PDF sahifalarini rasmga aylantirib, SAQLAMASDAN base64 ko‘rinishda qaytaradi.
    """

    def get(self, request, slug):
        try:
            standard = Standard.objects.get(slug=slug)
        except Standard.DoesNotExist:
            return Response({"detail": "Hujjat topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        pdf_path = standard.pdf.path

        try:
            # RAM ichida PDF sahifalarni o‘qish
            pages = convert_from_path(pdf_path, dpi=180)
        except Exception as e:
            return Response({"detail": f"PDFni o‘qishda xatolik: {str(e)}"}, status=500)

        images_base64 = []

        for page in pages:
            buffer = BytesIO()
            page.save(buffer, format="JPEG")
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            images_base64.append(f"data:image/jpeg;base64,{encoded}")

        return Response({
            "slug": slug,
            "page_count": len(images_base64),
            "images": images_base64
        })