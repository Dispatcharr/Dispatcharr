from django.urls import path

from . import api_views

app_name = "backups"

urlpatterns = [
    path("", api_views.list_backups, name="backup-list"),
    path("create/", api_views.create_backup, name="backup-create"),
    path("upload/", api_views.upload_backup, name="backup-upload"),
    path("schedule/", api_views.get_schedule, name="backup-schedule-get"),
    path("schedule/update/", api_views.update_schedule, name="backup-schedule-update"),
    path("status/<str:task_id>/", api_views.backup_status, name="backup-status"),
    path("<str:filename>/download-token/", api_views.get_download_token, name="backup-download-token"),
    path("<str:filename>/download/", api_views.download_backup, name="backup-download"),
    path("<str:filename>/delete/", api_views.delete_backup, name="backup-delete"),
    path("<str:filename>/restore/", api_views.restore_backup, name="backup-restore"),
]
