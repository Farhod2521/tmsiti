import pandas as pd

file_path = r"D:\FASTAPI\tmsiti\tmsiti\django_app\app_shnk\management\commands\shnk.xlsx"
df = pd.read_excel(file_path)

print(df.head())  # Birinchi 5 qatordan iborat qismini chiqarish
print(df.shape)   # Ustun va qatorlar sonini ko'rish
 