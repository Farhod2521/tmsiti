"""
Qo'lda yuklangan (Word/.doc/.docx) SHNQ tahrirlarini faylidan qayta o'qiydi — parser yangilanganda
(masalan, Word formatlari: tekislash, chekinish, raqamlash) eski tahrirlar ham yangi ko'rinishga o'tadi.

    python manage.py shnq_reparse --dry-run        # qaysilari qayta o'qilishini ko'rsatadi
    python manage.py shnq_reparse                  # barcha qo'lda yuklangan tahrirlar
    python manage.py shnq_reparse --shnk 12        # faqat bitta SHNQ
    python manage.py shnq_reparse --all            # lex.uz dan kelganlari ham
"""
from django.core.management.base import BaseCommand

from django_app.app_shnk.models import ShnkEdition
from django_app.app_shnk.shnq_docs import process_edition, rebuild_chain, resolve_lang


class Command(BaseCommand):
    help = "SHNQ tahrirlarini faylidan qayta o'qiydi (yangi parser bilan)"

    def add_arguments(self, parser):
        parser.add_argument("--shnk", type=int, help="Faqat shu SHNQ (id)")
        parser.add_argument("--all", action="store_true", help="lex.uz dan yuklanganlari ham")
        parser.add_argument("--dry-run", action="store_true", help="Faqat ro'yxatni ko'rsatish")

    def handle(self, *args, shnk=None, all=False, dry_run=False, **options):
        qs = ShnkEdition.objects.select_related("shnk").exclude(source_file="").order_by("shnk_id", "edition_date", "id")
        if not all:
            qs = qs.filter(source="manual")
        if shnk:
            qs = qs.filter(shnk_id=shnk)

        chains, ok, failed = set(), 0, 0
        for edition in qs:
            label = f"{edition.shnk.designation} [{edition.lang}] {edition.edition_date}"
            if dry_run:
                self.stdout.write(f"  {label}: {edition.source_file.name}")
                continue
            old_lang = edition.lang
            try:
                raw = process_edition(edition)
            except ValueError as exc:
                failed += 1
                edition.parse_error = str(exc)
                edition.save(update_fields=["parse_error", "updated_at"])
                self.stdout.write(self.style.WARNING(f"  ✗ {label}: {exc}"))
                continue
            edition.lang = resolve_lang(edition.lang, raw)
            edition.save(update_fields=["lang", "updated_at"])
            chains.update({(edition.shnk_id, old_lang), (edition.shnk_id, edition.lang)})
            ok += 1
            self.stdout.write(f"  ✓ {label}: {len(raw)} blok")

        for shnk_id, lang in sorted(chains):
            rebuild_chain(shnk_id, lang)

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Jami {qs.count()} ta tahrir qayta o'qiladi."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Qayta o'qildi: {ok}, xato: {failed}."))
