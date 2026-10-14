"""
tmsiti.uz/admin dashboardga kiradigan xodim yaratadi (yoki parolini yangilaydi).

    python manage.py shnq_admin_user admin                 # parol avtomatik yaratilib, bir marta ko'rsatiladi
    python manage.py shnq_admin_user admin --password ...  # o'zingiz bergan parol
    python manage.py shnq_admin_user admin --disable       # kirishni o'chirish

Parol almashtirilsa, shu xodimning barcha ochiq sessiyalari (tokenlari) bekor bo'ladi.
"""
import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Admin dashboard uchun xodim (login/parol) yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password", help="Bermasangiz — 16 belgili tasodifiy parol")
        parser.add_argument("--disable", action="store_true", help="Xodimning kirishini o'chirish")

    def handle(self, *args, username, password=None, disable=False, **options):
        User = get_user_model()
        user = User.objects.filter(username=username).first()

        if disable:
            if not user:
                raise CommandError(f"'{username}' topilmadi")
            user.is_staff = False
            user.save(update_fields=["is_staff"])
            self.stdout.write(self.style.SUCCESS(f"'{username}' ning admin panelga kirishi o'chirildi."))
            return

        generated = password is None
        if generated:
            alphabet = string.ascii_letters + string.digits
            password = "".join(secrets.choice(alphabet) for _ in range(16))
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("Parol yaroqsiz: " + " ".join(exc.messages))

        created = user is None
        if created:
            user = User(username=username)
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f"Xodim {'yaratildi' if created else 'yangilandi'}: {username}"))
        if generated:
            self.stdout.write(f"Parol: {password}")
            self.stdout.write("Parolni hozir saqlab oling — u boshqa ko'rsatilmaydi.")
