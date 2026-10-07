"""
Mavjud SHNQ tahrirlarining tilini matndan qayta aniqlaydi.

Avval faqat "uz" va "ru" bo'lgan; kirillcha o'zbek hujjatlar "uz" bo'lib saqlangan.
Bu buyruq ularni "kr" (kirill) ga o'tkazadi va zanjirlarni qayta solishtiradi.

    python manage.py shnq_detect_langs --dry-run   # faqat ko'rsatadi
    python manage.py shnq_detect_langs             # o'zgartiradi
"""
from django.core.management.base import BaseCommand

from django_app.app_shnk.models import ShnkEdition
from django_app.app_shnk.shnq_docs import rebuild_chain, resolve_lang


class Command(BaseCommand):
    help = "SHNQ tahrirlarining tilini (uz / kr / ru) matndan qayta aniqlaydi"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Hech narsani o'zgartirmasdan ko'rsatish")

    def handle(self, *args, dry_run=False, **options):
        chains = set()
        changed = 0
        for edition in ShnkEdition.objects.select_related("shnk").order_by("shnk_id", "id"):
            if not edition.raw_blocks:
                continue
            new_lang = resolve_lang(edition.lang, edition.raw_blocks)
            if new_lang == edition.lang:
                continue
            changed += 1
            self.stdout.write(f"{edition.shnk.designation} [{edition.edition_date}]: {edition.lang} -> {new_lang}")
            if not dry_run:
                chains.update({(edition.shnk_id, edition.lang), (edition.shnk_id, new_lang)})
                ShnkEdition.objects.filter(pk=edition.pk).update(lang=new_lang)

        for shnk_id, lang in chains:
            rebuild_chain(shnk_id, lang)

        verb = "o'zgaradi" if dry_run else "o'zgartirildi"
        self.stdout.write(self.style.SUCCESS(f"Jami {changed} ta tahrir tili {verb}."))
