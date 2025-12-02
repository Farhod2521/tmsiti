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
    

from django.core.cache import cache
from concurrent.futures import ThreadPoolExecutor
import hashlib

class StandardPdfToImagesAPIView(APIView):
    """
    PDF sahifalarini rasmga aylantirib, SAQLAMASDAN base64 ko'rinishda qaytaradi.
    """

    def get(self, request, slug):
        # 1. Cache qo'shish
        cache_key = f"pdf_images_{slug}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return Response(cached_data)

        try:
            standard = Standard.objects.only('pdf').get(slug=slug)
        except Standard.DoesNotExist:
            return Response(
                {"detail": "Hujjat topilmadi."}, 
                status=status.HTTP_404_NOT_FOUND
            )

        pdf_path = standard.pdf.path
        
        # 2. PDF fayl hash-ni tekshirish (agar fayl o'zgarmasa)
        file_hash = self._get_file_hash(pdf_path)
        hash_cache_key = f"pdf_hash_{slug}"
        
        if cache.get(hash_cache_key) == file_hash and cached_data:
            return Response(cached_data)

        try:
            # 3. Parallel processing - sahifalarni parallel o'qish
            pages = self._convert_pdf_parallel(pdf_path)
        except Exception as e:
            return Response(
                {"detail": f"PDFni o'qishda xatolik: {str(e)}"}, 
                status=500
            )

        # 4. Base64 encoding ni parallel qilish
        images_base64 = self._encode_images_parallel(pages)

        response_data = {
            "slug": slug,
            "page_count": len(images_base64),
            "images": images_base64
        }

        # 5. Cache-ga saqlash (1 soat muddat)
        cache.set(cache_key, response_data, timeout=3600)
        cache.set(hash_cache_key, file_hash, timeout=3600)

        return Response(response_data)

    def _get_file_hash(self, file_path):
        """Fayl hash hisoblash"""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            # Faqat birinchi 1MB ni o'qish tezlik uchun
            chunk = f.read(1024 * 1024)
            hasher.update(chunk)
        return hasher.hexdigest()

    def _convert_pdf_parallel(self, pdf_path, dpi=150):
        """PDF sahifalarini parallel o'qish"""
        try:
            # pdf2image ko'p core dan foydalanadi, lekin thread-safe emas
            pages = convert_from_path(
                pdf_path, 
                dpi=dpi,
                thread_count=4,  # CPU core lar soni
                grayscale=True,  # Rangli bo'lishi shart bo'lmasa
                size=(1600, None)  # O'lchamni limit qilish
            )
            return pages
        except:
            # Agar parallel xatolik bersa, oddiy usulga qaytish
            return convert_from_path(pdf_path, dpi=dpi)

    def _encode_images_parallel(self, pages):
        """Rasmlarni parallel ravishda base64 ga o'girish"""
        images_base64 = []
        
        def encode_page(page):
            buffer = BytesIO()
            # Sifatni optimal qilish
            page.save(
                buffer, 
                format="JPEG", 
                quality=85,  # 85% sifat optimal
                optimize=True
            )
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
        
        # Kichik PDF lar uchun parallel emas
        if len(pages) < 5:
            images_base64 = [encode_page(page) for page in pages]
        else:
            with ThreadPoolExecutor(max_workers=4) as executor:
                images_base64 = list(executor.map(encode_page, pages))
        
        return images_base64

    # OPTIONAL: Agar ko'p so'rov bo'lsa, background task qo'shish
    # Celery yoki Django Background Tasks dan foydalanish mumkin