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
    PDF sahifalarini rasmga aylantirib, base64 ko'rinishida qaytaradi.
    Pagination: ?page=2&limit=10
    """

    _thread_local = threading.local()

    def get(self, request, slug):
        # Pagination parametrlari
        page = int(request.GET.get("page", 1))
        limit = int(request.GET.get("limit", 10))

        # Sahifa boshlanishi / tugashi
        start_page = (page - 1) * limit + 1
        end_page = start_page + limit - 1

        cache_key = f"pdf_images_{slug}_{page}_{limit}"
        hash_cache_key = f"pdf_hash_{slug}"

        try:
            standard = Standard.objects.only('pdf').get(slug=slug)
        except Standard.DoesNotExist:
            return Response({"detail": "Hujjat topilmadi."}, status=404)

        pdf_path = standard.pdf.path

        # PDF hash
        file_hash = self._get_file_metadata_hash(pdf_path)
        old_hash = cache.get(hash_cache_key)

        # Agar PDF o‘zgarmagan bo‘lsa — cache'dan beramiz
        if old_hash == file_hash:
            cached_data = cache.get(cache_key)
            if cached_data:
                return Response(cached_data)

        # PDF o'zgargan bo'lsa — eski cache'ni o'chiramiz
        cache.delete(cache_key)
        cache.delete(hash_cache_key)

        # PDF umumiy sahifalar soni
        total_pages = self._get_total_pages(pdf_path)

        # End_page PDF dan oshib ketmasin
        end_page = min(end_page, total_pages)

        if start_page > total_pages:
            return Response({"detail": "Bu sahifa mavjud emas"}, status=404)

        try:
            pages = convert_from_path(
                pdf_path,
                dpi=120,
                first_page=start_page,
                last_page=end_page,
                thread_count=2,
                grayscale=True,
                size=(1200, None),
                fmt='jpeg',
                jpegopt={"quality": 80, "optimize": True, "progressive": True},
                strict=False,
                use_pdftocairo=True
            )
        except Exception as e:
            return Response({"detail": f"PDF konvertatsiya xatosi: {str(e)}"}, status=500)

        images_base64 = self._encode_images_optimized(pages)

        response_data = {
            "slug": slug,
            "page": page,
            "limit": limit,
            "page_count": len(images_base64),
            "total_pages": total_pages,
            "images": images_base64
        }

        # Yangi cache yozish
        cache.set(cache_key, response_data, timeout=1800)
        cache.set(hash_cache_key, file_hash, timeout=1800)

        return Response(response_data)

    # ===============================
    #   YORDAMCHI FUNKSIYALAR
    # ===============================

    def _get_file_metadata_hash(self, file_path):
        stat_info = os.stat(file_path)
        metadata = f"{stat_info.st_size}_{stat_info.st_mtime}"
        return hashlib.md5(metadata.encode()).hexdigest()

    def _get_total_pages(self, pdf_path):
        try:
            from pdf2image.pdf2image import pdfinfo_from_path
            info = pdfinfo_from_path(pdf_path)
            return info["Pages"]
        except:
            return 0

    def _convert_pdf_optimized(self, pdf_path, dpi=120, page_limit=10):
        try:
            first_page = 1
            last_page = min(page_limit, self._get_total_pages(pdf_path))

            if last_page < 1:
                return []

            pages = convert_from_path(
                pdf_path,
                dpi=dpi,
                first_page=first_page,
                last_page=last_page,
                thread_count=2,
                grayscale=True,
                size=(1200, None),
                fmt='jpeg',
                jpegopt={
                    "quality": 80,
                    "progressive": True,
                    "optimize": True
                },
                strict=False,
                use_pdftocairo=True
            )
            return pages

        except Exception:
            all_pages = convert_from_path(pdf_path, dpi=dpi)
            return all_pages[:page_limit]

    def _encode_images_optimized(self, pages):
        if not pages:
            return []

        images_base64 = []
        batch_size = 3

        for i in range(0, len(pages), batch_size):
            batch = pages[i:i+batch_size]
            with ThreadPoolExecutor(max_workers=2) as executor:
                batch_results = list(executor.map(self._encode_single_image, batch))
                images_base64.extend(batch_results)

        return images_base64

    def _encode_single_image(self, page):
        buffer = BytesIO()

        page.save(
            buffer,
            format="JPEG",
            quality=75,
            optimize=True,
            progressive=True
        )

        buffer.seek(0)

        if buffer.getbuffer().nbytes > 500 * 1024:
            buffer = self._compress_image_buffer(buffer)

        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def _compress_image_buffer(self, buffer, max_size_kb=300):
        buffer.seek(0)
        img = Image.open(buffer)

        for quality in [70, 60, 50]:
            new_buffer = io.BytesIO()
            img.save(new_buffer, format='JPEG', quality=quality, optimize=True)
            if new_buffer.tell() <= max_size_kb * 1024:
                return new_buffer

        return new_buffer




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
        








from .models import  Quiz, Customer


class QuizListAPIView(APIView):
    def get(self, request):
        quizzes = Quiz.objects.filter(status=True)

        data = []
        for quiz in quizzes:
            data.append({
                "id": quiz.id,
                "json": quiz.json,
                "status": quiz.status
            })

        return Response(data, status=status.HTTP_200_OK)
    
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny
@method_decorator(csrf_exempt, name='dispatch')
class CustomerCreateAPIView(APIView):
    authentication_classes = []   # 🔥 MUHIM
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data

        customer = Customer.objects.create(
            full_name=data.get("full_name"),
            phone=data.get("phone"),
            email=data.get("email"),
            corrent_ans=data.get("corrent_ans", 0),
            result=data.get("result", ""),
        )

        return Response(
            {"message": "Customer yaratildi", "id": customer.id},
            status=status.HTTP_201_CREATED
        )