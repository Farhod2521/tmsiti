from django.shortcuts import render

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Texnik_reglaament, Standard
from .serializers import TexnikReglaamentSerializer, StandardSerializer


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
import threading
from PIL import Image
import io
from pdf2image import convert_from_path
import os
class StandardPdfToImagesAPIView(APIView):
    """
    PDF sahifalarini rasmga aylantirib, SAQLAMASDAN base64 ko'rinishda qaytaradi.
    Faqat 10 ta sahifani ko'rsatadi.
    """

    # Thread local storage for expensive resources
    _thread_local = threading.local()

    def get(self, request, slug):
        # Faqat 10 ta sahifani ko'rsatish
        page_limit = 10
        
        # 1. Cache qo'shish (sahifa limiti bilan)
        cache_key = f"pdf_images_{slug}_{page_limit}"
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
        
        # 2. PDF fayl hash-ni tekshirish (faqat metadata)
        file_hash = self._get_file_metadata_hash(pdf_path)
        hash_cache_key = f"pdf_hash_{slug}"
        
        if cache.get(hash_cache_key) == file_hash and cached_data:
            return Response(cached_data)

        try:
            # 3. Faqat kerakli sahifalarni o'qish (1-10 sahifalar)
            pages = self._convert_pdf_optimized(pdf_path, page_limit=page_limit)
            
            # Agar sahifalar soni 10 dan kam bo'lsa
            actual_pages = min(len(pages), page_limit)
            pages = pages[:actual_pages]
            
        except Exception as e:
            return Response(
                {"detail": f"PDFni o'qishda xatolik: {str(e)}"}, 
                status=500
            )

        # 4. Base64 encoding ni parallel qilish (optimized)
        images_base64 = self._encode_images_optimized(pages)

        response_data = {
            "slug": slug,
            "page_count": len(images_base64),
            "total_pages": self._get_total_pages(pdf_path) if pages else 0,
            "images": images_base64,
            "note": f"Faqat dastlabki {len(images_base64)} sahifa ko'rsatilmoqda"
        }

        # 5. Cache-ga saqlash (30 daqiqa muddat)
        cache.set(cache_key, response_data, timeout=1800)
        cache.set(hash_cache_key, file_hash, timeout=1800)

        return Response(response_data)

    def _get_file_metadata_hash(self, file_path):
        """Fayl metadata hash hisoblash (tezroq)"""
        stat_info = os.stat(file_path)
        # Fayl hajmi va o'zgartirilish vaqti
        metadata = f"{stat_info.st_size}_{stat_info.st_mtime}"
        return hashlib.md5(metadata.encode()).hexdigest()

    def _get_total_pages(self, pdf_path):
        """PDF ning umumiy sahifalar sonini aniqlash"""
        try:
            # pdf2image orqali tezroq usul
            from pdf2image.pdf2image import pdfinfo_from_path
            info = pdfinfo_from_path(pdf_path)
            return info["Pages"]
        except:
            return 0

    def _convert_pdf_optimized(self, pdf_path, dpi=120, page_limit=10):
        """PDF sahifalarini optimal o'qish (faqat kerakli sahifalar)"""
        try:
            # Faqat kerakli sahifalarni o'qish
            first_page = 1
            last_page = min(page_limit, self._get_total_pages(pdf_path))
            
            if last_page < 1:
                return []
            
            # Optimized conversion parameters
            pages = convert_from_path(
                pdf_path, 
                dpi=dpi,
                first_page=first_page,
                last_page=last_page,
                thread_count=2,  # Kamroq thread (RAM tejash)
                grayscale=True,   # Faqat oq-qora
                size=(1200, None),  # Kichikroq o'lcham
                fmt='jpeg',       # JPEG formatda saqlash
                jpegopt={
                    "quality": 80,  # Sifatni pasaytirish
                    "progressive": True,
                    "optimize": True
                },
                strict=False,     # Xatolarga bardosh
                use_pdftocairo=True  # Tezroq konvertatsiya
            )
            return pages
        except Exception as e:
            # Fallback: oddiy usul
            try:
                all_pages = convert_from_path(pdf_path, dpi=dpi)
                return all_pages[:page_limit]
            except:
                raise e

    def _encode_images_optimized(self, pages):
        """Rasmlarni optimal base64 encoding"""
        if not pages:
            return []
        
        images_base64 = []
        
        # Kichik batch size bilan ishlash
        batch_size = 3
        
        for i in range(0, len(pages), batch_size):
            batch = pages[i:i+batch_size]
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                batch_results = list(executor.map(self._encode_single_image, batch))
                images_base64.extend(batch_results)
        
        return images_base64

    def _encode_single_image(self, page):
        """Bitta rasmni encode qilish"""
        buffer = BytesIO()
        
        # Optimized saqlash parametrlari
        page.save(
            buffer, 
            format="JPEG", 
            quality=75,           # 75% sifat (tejamkor)
            optimize=True,
            progressive=True      # Progressiv JPEG
        )
        
        buffer.seek(0)
        # Faqat kerakli qismini encode qilish
        if buffer.getbuffer().nbytes > 500 * 1024:  # Agar 500KB dan katta bo'lsa
            buffer = self._compress_image_buffer(buffer)
        
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def _compress_image_buffer(self, buffer, max_size_kb=300):
        """Rasmni qayta siqish agar hajmi katta bo'lsa"""

        
        buffer.seek(0)
        img = Image.open(buffer)
        
        # Quality ni bosqichma-bosqich pasaytirish
        for quality in [70, 60, 50]:
            new_buffer = io.BytesIO()
            img.save(new_buffer, format='JPEG', quality=quality, optimize=True)
            if new_buffer.tell() <= max_size_kb * 1024:
                return new_buffer
        
        return new_buffer

    # Agar barcha sahifalarni olish kerak bo'lsa (alohida endpoint)
    def get_all_pages(self, request, slug):
        """Barcha sahifalarni olish (alohida endpoint)"""
        # ... similar implementation without page_limit
        pass

    # OPTIONAL: Agar ko'p so'rov bo'lsa, background task qo'shish
    # Celery yoki Django Background Tasks dan foydalanish mumkin




class StandardListAPIView(APIView):
    """
    Standartlar ro'yxati — barcha tillardagi title/designation bilan.
    PDF qaytmaydi.
    """

    def get(self, request):
        try:
            standards = Standard.objects.all().order_by("-number")
            serializer = StandardSerializer(standards, many=True, context={"request": request})

            return Response({
                "success": True,
                "count": len(serializer.data),
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)