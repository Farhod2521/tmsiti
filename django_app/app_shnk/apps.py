from django.apps import AppConfig


class AppShnkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'django_app.app_shnk'

    def ready(self):
        from django.db import transaction
        from django.db.models.signals import post_save

        from .models import Shnk, ShnkEdition

        # Matn tahriri yo'q SHNQ ning PDF i almashtirilsa — qidiruv indeksi PDF dan yangilanadi
        # (tahriri borlari rebuild_chain() da yangilanadi)
        def reindex_pdf(sender, instance, **kwargs):
            if ShnkEdition.objects.filter(shnk_id=instance.pk).exists():
                return
            from .shnq_search import safe_index_shnk

            transaction.on_commit(lambda: safe_index_shnk(instance.pk))

        post_save.connect(reindex_pdf, sender=Shnk, dispatch_uid="shnq_search_reindex_pdf")
