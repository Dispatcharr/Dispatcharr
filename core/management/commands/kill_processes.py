# core/management/commands/kill_processes.py

import psutil
from core.redaction import redact_text
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Kills all processes with 'ffmpeg' or 'streamlink' in their name or command line."

    def handle(self, *args, **options):
        kill_count = 0

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = proc.info.get('name') or ''
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                lower_name = name.lower()
                lower_cmdline = cmdline.lower()

                if ('ffmpeg' in lower_name or 'ffmpeg' in lower_cmdline or
                    'streamlink' in lower_name or 'streamlink' in lower_cmdline):
                    self.stdout.write(f"Killing PID {proc.pid}: {name} {redact_text(cmdline)}")
                    proc.kill()
                    kill_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        self.stdout.write(self.style.SUCCESS(f"Killed {kill_count} processes."))
