import os
import openpyxl
from django.core.management.base import BaseCommand
from django_app.app_shnk.models import Subsystem, ShnkGroup, Shnk  

class Command(BaseCommand):
    help = "Import data from an Excel file into the database."

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help="Path to the Excel file")

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']

        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        wb = openpyxl.load_workbook(file_path)
        ws = wb.active  

        for index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):  
            row = list(row)  
            row = [(cell if cell is not None else "") for cell in row]  

            if len(row) < 7:  
                self.stdout.write(self.style.ERROR(f"⛔ Row {index} skipped (insufficient columns): {row}"))
                continue  

            row = row[:14] + [""] * (14 - len(row))  # 14 ustunga to‘ldirish
            row = row[:7]  

            subsystem_title, shnkgroup_title, designation, change, name_uz, name_ru, url = row  

            if not designation.strip():
                self.stdout.write(self.style.ERROR(f"⛔ Row {index} skipped: Designation is empty"))
                continue

            subsystem, _ = Subsystem.objects.get_or_create(title=subsystem_title.strip())
            shnkgroup, _ = ShnkGroup.objects.get_or_create(subsystem=subsystem, title=shnkgroup_title.strip())

            shnk, created = Shnk.objects.get_or_create(
                shnkgroup=shnkgroup,
                designation=designation.strip(),
                defaults={
                    'name_uz': name_uz.strip(),
                    'name_ru': name_ru.strip(),
                    'change': change.strip(),
                    'url': url.strip(),
                    'pdf_uz': None,
                    'pdf_ru': None
                }
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"✅ Row {index} added: {designation}"))
            else:
                self.stdout.write(self.style.WARNING(f"⚠️ Row {index} updated: {designation}"))

        self.stdout.write(self.style.SUCCESS("🎉 Successfully imported all data from Excel."))
