"""
Kirillcha ("kr") SHNQ tahrirlaridan lotincha ("uz") nusxa yaratadi.

Kirill tahrirlar o'zgarmaydi; lotincha tahriri yo'q SHNQ lar uchun har bir kirill
tahrirning o'girilgan nusxasi "uz" bo'lib qo'shiladi va zanjir qayta solishtiriladi.

    python manage.py shnq_latinize --dry-run      # faqat ko'rsatadi
    python manage.py shnq_latinize                # yaratadi
    python manage.py shnq_latinize --shnk 12      # faqat bitta SHNQ
    python manage.py shnq_latinize --replace      # mavjud lotincha tahrirlarni o'chirib, qayta yaratadi
"""
import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from django_app.app_shnk.models import ShnkEdition
from django_app.app_shnk.shnq_docs import blocks_to_latin, content_hash, rebuild_chain, to_latin


class Command(BaseCommand):
    help = "Kirillcha SHNQ tahrirlaridan lotincha (uz) nusxa yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Hech narsani o'zgartirmasdan ko'rsatish")
        parser.add_argument("--shnk", type=int, help="Faqat shu SHNQ (id)")
        parser.add_argument("--replace", action="store_true", help="Mavjud lotincha tahrirlarni o'chirib, qayta yaratish")

    def handle(self, *args, dry_run=False, shnk=None, replace=False, **options):
        qs = ShnkEdition.objects.select_related("shnk").filter(lang="kr").order_by("shnk_id", "edition_date", "id")
        if shnk:
            qs = qs.filter(shnk_id=shnk)

        by_shnk = {}
        for edition in qs:
            by_shnk.setdefault(edition.shnk_id, []).append(edition)
        if not by_shnk:
            self.stdout.write(self.style.WARNING("Kirillcha (kr) tahrirlar topilmadi."))
            return

        created = skipped = 0
        for shnk_id, editions in by_shnk.items():
            designation = editions[0].shnk.designation
            existing = ShnkEdition.objects.filter(shnk_id=shnk_id, lang="uz")
            if existing.exists() and not replace:
                skipped += 1
                self.stdout.write(f"{designation}: lotincha tahriri bor — o'tkazildi (--replace bilan qayta yaratiladi)")
                continue

            self.stdout.write(f"{designation}: {len(editions)} ta tahrir -> uz")
            if dry_run:
                sample = next((b.get("text") or b.get("key") for b in editions[0].raw_blocks or [] if b.get("key")), "")
                if sample:
                    self.stdout.write(f"   namuna: {to_latin(sample[:120])}")
                created += len(editions)
                continue

            with transaction.atomic():
                for old in existing:
                    old.source_file.delete(save=False)
                    old.delete()
                for edition in editions:
                    self._copy(edition)
                    created += 1
            rebuild_chain(shnk_id, "uz")

        verb = "yaratiladi" if dry_run else "yaratildi"
        self.stdout.write(self.style.SUCCESS(f"Jami {created} ta lotincha tahrir {verb}, {skipped} ta SHNQ o'tkazildi."))

    def _copy(self, edition):
        raw = blocks_to_latin(edition.raw_blocks or [])
        copy = ShnkEdition(
            shnk_id=edition.shnk_id,
            lang="uz",
            edition_date=edition.edition_date,
            note=to_latin(edition.note or "")[:1000],
            source=edition.source,
            raw_blocks=raw,
            content_hash=content_hash(raw),
            parse_error=edition.parse_error,
        )
        # Fayl alohida nusxalanadi: lotincha tahrir o'chirilganda kirillchaniki saqlanib qoladi
        if edition.source_file:
            try:
                with edition.source_file.open("rb") as f:
                    data = f.read()
                copy.source_file.save(os.path.basename(edition.source_file.name), ContentFile(data), save=False)
            except FileNotFoundError:
                copy.source_file = edition.source_file.name
        copy.save()
        return copy
