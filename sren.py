import os
import django
import pandas as pd

# Django sozlamalarini yuklash
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from django_app.app_shnk.models import SREN, SREN_SHNQ  # ← 'yourapp' ni o'zingizning app nomi bilan almashtiring

# Excel faylni o'qish
df = pd.read_excel("sren.xlsx")

# Har bir qatorni o'qib, bazaga yozish
for _, row in df.iterrows():
    sren_designation = row['sren_designation']
    sren_name_uz = row['sren_name_uz']
    sren_shnk_designation = row['sren_shnk_designation']
    sren_shnk_name_uz = row['sren_shnk_name_uz']

    # SREN modelini yaratish yoki topish
    sren_obj, _ = SREN.objects.get_or_create(
        designation=sren_designation,
        defaults={'name': sren_name_uz}
    )

    # SREN_SHNQ modelini yaratish yoki topish
    SREN_SHNQ.objects.get_or_create(
        sren=sren_obj,
        designation=sren_shnk_designation,
        defaults={'name': sren_shnk_name_uz}
    )

print("✅ Ma'lumotlar bazaga muvaffaqiyatli yozildi.")
