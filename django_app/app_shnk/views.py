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




class StandardListAPIView(APIView):
    """
    3 ta til uchun Standard modelini ro'yxatini qaytaruvchi APIView
    GET parametrlarida ?lang= uz, ?lang=ru, ?lang=en
    """
    
    def get(self, request, format=None):
        """Tilga qarab standartlar ro'yxatini qaytarish"""
        
        # Til parametrini olish (?lang=uz, ?lang=ru, ?lang=en)
        lang = request.GET.get('lang', 'uz')
        
        # Tahrirlangan til uchun field nomlari
        title_field = f'title_{lang}'
        designation_field = f'designation_{lang}'
        
        # Modelda til maydonlari mavjudligini tekshirish
        # Agar modelda til maydonlari bo'lmasa, default fieldlardan foydalanish
        try:
            # Standartlarni olish
            standards = Standard.objects.all()
            
            # Har bir standart uchun tilga mos ma'lumotlarni tayyorlash
            data = []
            for standard in standards:
                standard_data = {
                    'id': standard.id,
                    'slug': standard.slug,
                    'number': standard.number,
                    'pdf': request.build_absolute_uri(standard.pdf.url) if standard.pdf else None,
                    'created_at': standard.created_at,
                    'updated_at': standard.updated_at,
                }
                
                # Agar modelda title_uz, title_ru, title_en maydonlari bo'lsa
                if hasattr(standard, title_field):
                    standard_data['title'] = getattr(standard, title_field, '')
                else:
                    # Agar til maydonlari bo'lmasa, default title ishlatiladi
                    standard_data['title'] = standard.title
                
                # Agar modelda designation_uz, designation_ru, designation_en maydonlari bo'lsa
                if hasattr(standard, designation_field):
                    standard_data['designation'] = getattr(standard, designation_field, '')
                else:
                    # Agar til maydonlari bo'lmasa, default designation ishlatiladi
                    standard_data['designation'] = standard.designation
                
                data.append(standard_data)
            
            return Response({
                'success': True,
                'language': lang,
                'count': len(data),
                'data': data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)