# manage.py
import os
import sys

if __name__ == "__main__":
    env = os.getenv('DJANGO_ENV', 'development')  # Standart holatda development
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{env}")

    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
