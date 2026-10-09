"""
lex.uz dan SHNQ va qonunlarni avtomatik yuklash.

Admin paneldagi "Boshlash" tugmasi shu buyruqni alohida jarayon sifatida ishga tushiradi (--job).
Qo'lda yoki cron orqali ham ishlatish mumkin:

    python manage.py lex_sync                       # hammasi + havola qilingan qonunlar
    python manage.py lex_sync --scope missing       # faqat matni yo'q SHNQ lar
    python manage.py lex_sync --mode replace        # mavjud matnlarni o'chirib, qaytadan yuklash
    python manage.py lex_sync --shnk 12 --shnk 15   # faqat shu SHNQ lar
    python manage.py lex_sync --no-laws             # qonunlarsiz

Muntazam yangilash (cron, har kecha 02:00):
    0 2 * * * cd /path/to/tmsiti && DJANGO_ENV=production venv/bin/python manage.py lex_sync --scope all
"""
from django.core.management.base import BaseCommand, CommandError

from django_app.app_shnk.lex_sync import active_job, run_job
from django_app.app_shnk.models import LexSyncJob


class Command(BaseCommand):
    help = "lex.uz dan SHNQ va qonun matnlarini avtomatik yuklaydi"

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, help="Admin paneldan yaratilgan jarayon raqami")
        parser.add_argument("--scope", choices=["all", "missing", "failed"], default="all")
        parser.add_argument("--mode", choices=["update", "replace"], default="update")
        parser.add_argument("--shnk", type=int, action="append", help="Faqat shu SHNQ (bir necha marta berish mumkin)")
        parser.add_argument("--no-laws", action="store_true", help="Havola qilingan qonunlarni yuklamaslik")
        parser.add_argument("--delay", type=float, default=2.0, help="lex.uz so'rovlari orasidagi pauza (soniya)")
        parser.add_argument("--max-laws", type=int, default=300, help="Bir jarayonda yuklanadigan qonunlar soni chegarasi")

    def handle(self, *args, **opts):
        if opts["job"]:
            if not LexSyncJob.objects.filter(pk=opts["job"]).exists():
                raise CommandError(f"Jarayon #{opts['job']} topilmadi")
            job_id = opts["job"]
        else:
            if active_job():
                raise CommandError("Boshqa import jarayoni ishlab turibdi")
            job_id = LexSyncJob.objects.create(params={
                "scope": opts["scope"],
                "mode": opts["mode"],
                "laws": not opts["no_laws"],
                "shnk_ids": opts["shnk"] or [],
                "delay": opts["delay"],
                "max_laws": opts["max_laws"],
                "source": "cli",
            }).pk

        run_job(job_id)
        job = LexSyncJob.objects.get(pk=job_id)
        self.stdout.write(job.log.splitlines()[-1] if job.log else "")
        self.stdout.write(self.style.SUCCESS(f"Jarayon #{job.pk}: {job.get_status_display()} — {job.counters}"))
