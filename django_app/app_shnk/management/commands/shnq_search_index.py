"""
SHNQ ichidan qidiruv indeksini (to'liq) qayta yaratadi.

Matn tahriri bor hujjatlar — oxirgi tahrir bandlari bo'yicha, qolganlari — PDF sahifalari bo'yicha.
Birinchi ishga tushirishda MySQL FULLTEXT indeksini ham yaratadi.

    python manage.py shnq_search_index            # hammasi
    python manage.py shnq_search_index --shnk 12  # faqat bitta SHNQ
    python manage.py shnq_search_index --test "yong'in xavfsizligi"   # qidiruvni sinash
"""
from django.core.management.base import BaseCommand

from django_app.app_shnk.models import Shnk
from django_app.app_shnk.shnq_search import ensure_fulltext_index, index_shnk, search


class Command(BaseCommand):
    help = "SHNQ ichidan qidiruv indeksini qayta yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--shnk", type=int, help="Faqat shu SHNQ (id)")
        parser.add_argument("--test", help="Indeksdan keyin shu so'z bo'yicha qidirib ko'rsatish")

    def handle(self, *args, shnk=None, test=None, **options):
        if ensure_fulltext_index():
            self.stdout.write("FULLTEXT indeks yaratildi.")

        ids = [shnk] if shnk else list(Shnk.objects.order_by("id").values_list("id", flat=True))
        total = empty = 0
        for n, shnk_id in enumerate(ids, start=1):
            count = index_shnk(shnk_id)
            total += count
            empty += not count
            if n % 20 == 0 or n == len(ids):
                self.stdout.write(f"  {n}/{len(ids)} hujjat, {total} band")

        self.stdout.write(self.style.SUCCESS(
            f"Indekslandi: {len(ids)} hujjat, {total} band. Matni topilmagan hujjatlar: {empty}."
        ))

        if test:
            results = search(test)
            self.stdout.write(f"\n'{test}' — {len(results)} ta hujjat topildi:")
            for doc in results[:10]:
                title = Shnk.objects.filter(pk=doc["id"]).values_list("designation", flat=True).first()
                self.stdout.write(f"  {title} ({doc['count']} band): {doc['hits'][0]['snippet'][:150]}")
