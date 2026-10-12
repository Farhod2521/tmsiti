"""
Sayt statistikasi uchun IP -> viloyat bazasini (DB-IP Lite, bepul, CC BY 4.0) yuklab oladi.

    python manage.py geoip_update

Baza oyiga bir marta yangilanadi; cron (har oyning 3-kuni):
    0 4 3 * * cd /path/to/tmsiti && DJANGO_ENV=production venv/bin/python manage.py geoip_update
"""
import datetime
import gzip
import os
import shutil
import tempfile
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from django_app.app_shnk.analytics import geoip_path

URL = "https://download.db-ip.com/free/dbip-city-lite-{:%Y-%m}.mmdb.gz"


class Command(BaseCommand):
    help = "IP -> viloyat bazasini (DB-IP Lite) yuklab oladi"

    def handle(self, *args, **opts):
        target = geoip_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        today = datetime.date.today()
        months = [today, (today.replace(day=1) - datetime.timedelta(days=1))]  # joriy yoki o'tgan oy

        for month in months:
            url = URL.format(month)
            self.stdout.write(f"Yuklanmoqda: {url}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=300) as resp, tempfile.NamedTemporaryFile(
                    dir=os.path.dirname(target), delete=False
                ) as tmp:
                    with gzip.GzipFile(fileobj=resp) as gz:
                        shutil.copyfileobj(gz, tmp)
                os.replace(tmp.name, target)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  bo'lmadi: {exc}"))
                if "tmp" in locals() and os.path.exists(tmp.name):
                    os.remove(tmp.name)
                continue
            size = os.path.getsize(target) // (1024 * 1024)
            self.stdout.write(self.style.SUCCESS(f"Tayyor: {target} ({size} MB). Django ni qayta ishga tushiring."))
            return
        raise CommandError("Bazani yuklab bo'lmadi")
