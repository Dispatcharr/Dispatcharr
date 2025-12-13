import json
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from . import services

User = get_user_model()


class BackupServicesTestCase(TestCase):
    """Test cases for backup services"""

    def setUp(self):
        self.temp_backup_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if Path(self.temp_backup_dir).exists():
            shutil.rmtree(self.temp_backup_dir)

    @patch('apps.backups.services.settings')
    def test_get_backup_dir_creates_directory(self, mock_settings):
        """Test that get_backup_dir creates the directory if it doesn't exist"""
        mock_settings.BACKUP_ROOT = self.temp_backup_dir

        with patch('apps.backups.services.Path') as mock_path:
            mock_path_instance = MagicMock()
            mock_path_instance.mkdir = MagicMock()
            mock_path.return_value = mock_path_instance

            services.get_backup_dir()
            mock_path_instance.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.services._is_postgresql')
    @patch('apps.backups.services._dump_sqlite')
    def test_create_backup_success_sqlite(self, mock_dump_sqlite, mock_is_pg, mock_get_backup_dir):
        """Test successful backup creation with SQLite"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)
        mock_is_pg.return_value = False

        # Mock SQLite dump to create a temp file
        def mock_dump(output_file):
            output_file.write_text("sqlite dump")

        mock_dump_sqlite.side_effect = mock_dump

        result = services.create_backup()

        self.assertIsInstance(result, Path)
        self.assertTrue(result.exists())
        self.assertTrue(result.name.startswith('dispatcharr-backup-'))
        self.assertTrue(result.name.endswith('.zip'))

        # Verify the backup contains expected files
        with ZipFile(result, 'r') as zf:
            names = zf.namelist()
            self.assertIn('database.sqlite3', names)
            self.assertIn('metadata.json', names)

            # Check metadata
            metadata = json.loads(zf.read('metadata.json'))
            self.assertEqual(metadata['version'], 2)
            self.assertEqual(metadata['database_type'], 'sqlite')

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.services._is_postgresql')
    @patch('apps.backups.services._dump_postgresql')
    def test_create_backup_success_postgresql(self, mock_dump_pg, mock_is_pg, mock_get_backup_dir):
        """Test successful backup creation with PostgreSQL"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)
        mock_is_pg.return_value = True

        # Mock PostgreSQL dump to create a temp file
        def mock_dump(output_file):
            output_file.write_bytes(b"pg dump data")

        mock_dump_pg.side_effect = mock_dump

        result = services.create_backup()

        self.assertIsInstance(result, Path)
        self.assertTrue(result.exists())

        # Verify the backup contains expected files
        with ZipFile(result, 'r') as zf:
            names = zf.namelist()
            self.assertIn('database.dump', names)
            self.assertIn('metadata.json', names)

            # Check metadata
            metadata = json.loads(zf.read('metadata.json'))
            self.assertEqual(metadata['version'], 2)
            self.assertEqual(metadata['database_type'], 'postgresql')

    @patch('apps.backups.services.get_backup_dir')
    def test_list_backups_empty(self, mock_get_backup_dir):
        """Test listing backups when none exist"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        result = services.list_backups()

        self.assertEqual(result, [])

    @patch('apps.backups.services.get_backup_dir')
    def test_list_backups_with_files(self, mock_get_backup_dir):
        """Test listing backups with existing backup files"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir

        # Create a fake backup file
        test_backup = backup_dir / "dispatcharr-backup-2025.01.01.12.00.00.zip"
        test_backup.write_text("fake backup content")

        result = services.list_backups()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], test_backup.name)
        self.assertIn('size', result[0])
        self.assertIn('created', result[0])

    @patch('apps.backups.services.get_backup_dir')
    def test_delete_backup_success(self, mock_get_backup_dir):
        """Test successful backup deletion"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir

        # Create a fake backup file
        test_backup = backup_dir / "dispatcharr-backup-test.zip"
        test_backup.write_text("fake backup content")

        self.assertTrue(test_backup.exists())

        services.delete_backup(test_backup.name)

        self.assertFalse(test_backup.exists())

    @patch('apps.backups.services.get_backup_dir')
    def test_delete_backup_not_found(self, mock_get_backup_dir):
        """Test deleting a non-existent backup raises error"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        with self.assertRaises(FileNotFoundError):
            services.delete_backup("nonexistent-backup.zip")

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.services._is_postgresql')
    @patch('apps.backups.services._restore_postgresql')
    def test_restore_backup_postgresql(self, mock_restore_pg, mock_is_pg, mock_get_backup_dir):
        """Test successful restoration of PostgreSQL backup"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir
        mock_is_pg.return_value = True

        # Create PostgreSQL backup file
        backup_file = backup_dir / "test-backup.zip"
        with ZipFile(backup_file, 'w') as zf:
            zf.writestr('database.dump', b'pg dump data')
            zf.writestr('metadata.json', json.dumps({
                'version': 2,
                'database_type': 'postgresql',
                'database_file': 'database.dump'
            }))

        services.restore_backup(backup_file)

        mock_restore_pg.assert_called_once()

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.services._is_postgresql')
    @patch('apps.backups.services._restore_sqlite')
    def test_restore_backup_sqlite(self, mock_restore_sqlite, mock_is_pg, mock_get_backup_dir):
        """Test successful restoration of SQLite backup"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir
        mock_is_pg.return_value = False

        # Create SQLite backup file
        backup_file = backup_dir / "test-backup.zip"
        with ZipFile(backup_file, 'w') as zf:
            zf.writestr('database.sqlite3', 'sqlite data')
            zf.writestr('metadata.json', json.dumps({
                'version': 2,
                'database_type': 'sqlite',
                'database_file': 'database.sqlite3'
            }))

        services.restore_backup(backup_file)

        mock_restore_sqlite.assert_called_once()

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.services._is_postgresql')
    def test_restore_backup_database_type_mismatch(self, mock_is_pg, mock_get_backup_dir):
        """Test restore fails when database type doesn't match"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir
        mock_is_pg.return_value = True  # Current system is PostgreSQL

        # Create SQLite backup file
        backup_file = backup_dir / "test-backup.zip"
        with ZipFile(backup_file, 'w') as zf:
            zf.writestr('database.sqlite3', 'sqlite data')
            zf.writestr('metadata.json', json.dumps({
                'version': 2,
                'database_type': 'sqlite',  # Backup is SQLite
                'database_file': 'database.sqlite3'
            }))

        with self.assertRaises(ValueError) as context:
            services.restore_backup(backup_file)

        self.assertIn('mismatch', str(context.exception).lower())

    def test_restore_backup_not_found(self):
        """Test restoring from non-existent backup file"""
        fake_path = Path("/tmp/nonexistent-backup-12345.zip")

        with self.assertRaises(FileNotFoundError):
            services.restore_backup(fake_path)

    @patch('apps.backups.services.get_backup_dir')
    def test_restore_backup_missing_metadata(self, mock_get_backup_dir):
        """Test restoring from backup without metadata.json"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir

        # Create a backup file missing metadata.json
        backup_file = backup_dir / "invalid-backup.zip"
        with ZipFile(backup_file, 'w') as zf:
            zf.writestr('database.dump', b'fake dump data')

        with self.assertRaises(ValueError) as context:
            services.restore_backup(backup_file)

        self.assertIn('metadata.json', str(context.exception))

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.services._is_postgresql')
    def test_restore_backup_missing_database(self, mock_is_pg, mock_get_backup_dir):
        """Test restoring from backup missing database dump"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir
        mock_is_pg.return_value = True

        # Create backup file missing database dump
        backup_file = backup_dir / "invalid-backup.zip"
        with ZipFile(backup_file, 'w') as zf:
            zf.writestr('metadata.json', json.dumps({
                'version': 2,
                'database_type': 'postgresql',
                'database_file': 'database.dump'
            }))

        with self.assertRaises(ValueError) as context:
            services.restore_backup(backup_file)

        self.assertIn('database.dump', str(context.exception))


class BackupAPITestCase(TestCase):
    """Test cases for backup API endpoints"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
        self.temp_backup_dir = tempfile.mkdtemp()

    def get_auth_header(self, user):
        """Helper method to get JWT auth header for a user"""
        refresh = RefreshToken.for_user(user)
        return f'Bearer {str(refresh.access_token)}'

    def tearDown(self):
        import shutil
        if Path(self.temp_backup_dir).exists():
            shutil.rmtree(self.temp_backup_dir)

    def test_list_backups_requires_admin(self):
        """Test that listing backups requires admin privileges"""
        url = '/api/backups/'

        # Unauthenticated request
        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 403])

        # Regular user request
        response = self.client.get(url, HTTP_AUTHORIZATION=self.get_auth_header(self.user))
        self.assertIn(response.status_code, [401, 403])

    @patch('apps.backups.services.list_backups')
    def test_list_backups_success(self, mock_list_backups):
        """Test successful backup listing"""
        mock_list_backups.return_value = [
            {
                'name': 'backup-test.zip',
                'size': 1024,
                'created': '2025-01-01T12:00:00'
            }
        ]

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'backup-test.zip')

    def test_create_backup_requires_admin(self):
        """Test that creating backups requires admin privileges"""
        url = '/api/backups/create/'

        # Unauthenticated request
        response = self.client.post(url)
        self.assertIn(response.status_code, [401, 403])

        # Regular user request
        response = self.client.post(url, HTTP_AUTHORIZATION=self.get_auth_header(self.user))
        self.assertIn(response.status_code, [401, 403])

    @patch('apps.backups.tasks.create_backup_task.delay')
    def test_create_backup_success(self, mock_create_task):
        """Test successful backup creation via API (async task)"""
        mock_task = MagicMock()
        mock_task.id = 'test-task-id-123'
        mock_create_task.return_value = mock_task

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/create/'
        response = self.client.post(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertIn('task_id', data)
        self.assertIn('task_token', data)
        self.assertEqual(data['task_id'], 'test-task-id-123')

    @patch('apps.backups.tasks.create_backup_task.delay')
    def test_create_backup_failure(self, mock_create_task):
        """Test backup creation failure handling"""
        mock_create_task.side_effect = Exception("Failed to start task")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/create/'
        response = self.client.post(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn('detail', data)

    @patch('apps.backups.services.get_backup_dir')
    def test_download_backup_success(self, mock_get_backup_dir):
        """Test successful backup download"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir

        # Create a test backup file
        backup_file = backup_dir / "test-backup.zip"
        backup_file.write_text("test backup content")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/test-backup.zip/download/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')

    @patch('apps.backups.services.get_backup_dir')
    def test_download_backup_not_found(self, mock_get_backup_dir):
        """Test downloading non-existent backup"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/nonexistent.zip/download/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 404)

    @patch('apps.backups.services.delete_backup')
    def test_delete_backup_success(self, mock_delete_backup):
        """Test successful backup deletion via API"""
        mock_delete_backup.return_value = None

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/test-backup.zip/delete/'
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 204)
        mock_delete_backup.assert_called_once_with('test-backup.zip')

    @patch('apps.backups.services.delete_backup')
    def test_delete_backup_not_found(self, mock_delete_backup):
        """Test deleting non-existent backup via API"""
        mock_delete_backup.side_effect = FileNotFoundError("Not found")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/nonexistent.zip/delete/'
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 404)

    def test_upload_backup_requires_file(self):
        """Test that upload requires a file"""
        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/upload/'
        response = self.client.post(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('No file uploaded', data['detail'])

    @patch('apps.backups.services.get_backup_dir')
    def test_upload_backup_success(self, mock_get_backup_dir):
        """Test successful backup upload"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        # Create a fake backup file
        fake_backup = BytesIO(b"fake backup content")
        fake_backup.name = 'uploaded-backup.zip'

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/upload/'
        response = self.client.post(url, {'file': fake_backup}, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn('filename', data)

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.tasks.restore_backup_task.delay')
    def test_restore_backup_success(self, mock_restore_task, mock_get_backup_dir):
        """Test successful backup restoration via API (async task)"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir

        mock_task = MagicMock()
        mock_task.id = 'test-restore-task-456'
        mock_restore_task.return_value = mock_task

        # Create a test backup file
        backup_file = backup_dir / "test-backup.zip"
        backup_file.write_text("test backup content")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/test-backup.zip/restore/'
        response = self.client.post(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertIn('task_id', data)
        self.assertIn('task_token', data)
        self.assertEqual(data['task_id'], 'test-restore-task-456')

    @patch('apps.backups.services.get_backup_dir')
    def test_restore_backup_not_found(self, mock_get_backup_dir):
        """Test restoring from non-existent backup via API"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/nonexistent.zip/restore/'
        response = self.client.post(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 404)

    # --- Backup Status Endpoint Tests ---

    def test_backup_status_requires_auth_or_token(self):
        """Test that backup_status requires auth or valid token"""
        url = '/api/backups/status/fake-task-id/'

        # Unauthenticated request without token
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_backup_status_invalid_token(self):
        """Test that backup_status rejects invalid tokens"""
        url = '/api/backups/status/fake-task-id/?token=invalid-token'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    @patch('apps.backups.api_views.AsyncResult')
    def test_backup_status_with_admin_auth(self, mock_async_result):
        """Test backup_status with admin authentication"""
        mock_result = MagicMock()
        mock_result.ready.return_value = False
        mock_result.failed.return_value = False
        mock_result.state = 'PENDING'
        mock_async_result.return_value = mock_result

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/status/test-task-id/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['state'], 'pending')

    @patch('apps.backups.api_views.AsyncResult')
    @patch('apps.backups.api_views._verify_task_token')
    def test_backup_status_with_valid_token(self, mock_verify, mock_async_result):
        """Test backup_status with valid token"""
        mock_verify.return_value = True
        mock_result = MagicMock()
        mock_result.ready.return_value = True
        mock_result.get.return_value = {'status': 'completed', 'filename': 'test.zip'}
        mock_async_result.return_value = mock_result

        url = '/api/backups/status/test-task-id/?token=valid-token'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['state'], 'completed')

    @patch('apps.backups.api_views.AsyncResult')
    def test_backup_status_task_failed(self, mock_async_result):
        """Test backup_status when task failed"""
        mock_result = MagicMock()
        mock_result.ready.return_value = True
        mock_result.get.return_value = {'status': 'failed', 'error': 'Something went wrong'}
        mock_async_result.return_value = mock_result

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/status/test-task-id/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['state'], 'failed')
        self.assertIn('Something went wrong', data['error'])

    # --- Download Token Endpoint Tests ---

    def test_get_download_token_requires_admin(self):
        """Test that get_download_token requires admin privileges"""
        url = '/api/backups/test.zip/download-token/'

        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 403])

        response = self.client.get(url, HTTP_AUTHORIZATION=self.get_auth_header(self.user))
        self.assertIn(response.status_code, [401, 403])

    @patch('apps.backups.services.get_backup_dir')
    def test_get_download_token_success(self, mock_get_backup_dir):
        """Test successful download token generation"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir

        # Create a test backup file
        backup_file = backup_dir / "test-backup.zip"
        backup_file.write_text("test content")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/test-backup.zip/download-token/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('token', data)
        self.assertEqual(len(data['token']), 32)

    @patch('apps.backups.services.get_backup_dir')
    def test_get_download_token_not_found(self, mock_get_backup_dir):
        """Test download token for non-existent file"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/nonexistent.zip/download-token/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 404)

    # --- Download with Token Auth Tests ---

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.api_views._verify_task_token')
    def test_download_backup_with_valid_token(self, mock_verify, mock_get_backup_dir):
        """Test downloading backup with valid token (no auth header)"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir
        mock_verify.return_value = True

        # Create a test backup file
        backup_file = backup_dir / "test-backup.zip"
        backup_file.write_text("test backup content")

        url = '/api/backups/test-backup.zip/download/?token=valid-token'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    @patch('apps.backups.services.get_backup_dir')
    def test_download_backup_invalid_token(self, mock_get_backup_dir):
        """Test downloading backup with invalid token"""
        mock_get_backup_dir.return_value = Path(self.temp_backup_dir)

        url = '/api/backups/test-backup.zip/download/?token=invalid-token'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    @patch('apps.backups.services.get_backup_dir')
    @patch('apps.backups.tasks.restore_backup_task.delay')
    def test_restore_backup_task_start_failure(self, mock_restore_task, mock_get_backup_dir):
        """Test restore task start failure via API"""
        backup_dir = Path(self.temp_backup_dir)
        mock_get_backup_dir.return_value = backup_dir
        mock_restore_task.side_effect = Exception("Failed to start restore task")

        # Create a test backup file
        backup_file = backup_dir / "test-backup.zip"
        backup_file.write_text("test content")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/test-backup.zip/restore/'
        response = self.client.post(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn('detail', data)

    def test_get_schedule_requires_admin(self):
        """Test that getting schedule requires admin privileges"""
        url = '/api/backups/schedule/'

        # Unauthenticated request
        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 403])

        # Regular user request
        response = self.client.get(url, HTTP_AUTHORIZATION=self.get_auth_header(self.user))
        self.assertIn(response.status_code, [401, 403])

    @patch('apps.backups.api_views.get_schedule_settings')
    def test_get_schedule_success(self, mock_get_settings):
        """Test successful schedule retrieval"""
        mock_get_settings.return_value = {
            'enabled': True,
            'frequency': 'daily',
            'time': '03:00',
            'day_of_week': 0,
            'retention_count': 5,
            'cron_expression': '',
        }

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/schedule/'
        response = self.client.get(url, HTTP_AUTHORIZATION=auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['enabled'], True)
        self.assertEqual(data['frequency'], 'daily')
        self.assertEqual(data['retention_count'], 5)

    def test_update_schedule_requires_admin(self):
        """Test that updating schedule requires admin privileges"""
        url = '/api/backups/schedule/update/'

        # Unauthenticated request
        response = self.client.put(url, {}, content_type='application/json')
        self.assertIn(response.status_code, [401, 403])

        # Regular user request
        response = self.client.put(
            url,
            {},
            content_type='application/json',
            HTTP_AUTHORIZATION=self.get_auth_header(self.user)
        )
        self.assertIn(response.status_code, [401, 403])

    @patch('apps.backups.api_views.update_schedule_settings')
    def test_update_schedule_success(self, mock_update_settings):
        """Test successful schedule update"""
        mock_update_settings.return_value = {
            'enabled': True,
            'frequency': 'weekly',
            'time': '02:00',
            'day_of_week': 1,
            'retention_count': 10,
            'cron_expression': '',
        }

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/schedule/update/'
        response = self.client.put(
            url,
            {'enabled': True, 'frequency': 'weekly', 'time': '02:00', 'day_of_week': 1, 'retention_count': 10},
            content_type='application/json',
            HTTP_AUTHORIZATION=auth_header
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['frequency'], 'weekly')
        self.assertEqual(data['day_of_week'], 1)

    @patch('apps.backups.api_views.update_schedule_settings')
    def test_update_schedule_validation_error(self, mock_update_settings):
        """Test schedule update with invalid data"""
        mock_update_settings.side_effect = ValueError("frequency must be 'daily' or 'weekly'")

        auth_header = self.get_auth_header(self.admin_user)
        url = '/api/backups/schedule/update/'
        response = self.client.put(
            url,
            {'frequency': 'invalid'},
            content_type='application/json',
            HTTP_AUTHORIZATION=auth_header
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('frequency', data['detail'])


class BackupSchedulerTestCase(TestCase):
    """Test cases for backup scheduler"""

    databases = {'default'}

    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        from core.models import CoreSettings
        # Clean up any existing settings
        CoreSettings.objects.filter(key__startswith='backup_').delete()

    def tearDown(self):
        from core.models import CoreSettings
        from django_celery_beat.models import PeriodicTask
        CoreSettings.objects.filter(key__startswith='backup_').delete()
        PeriodicTask.objects.filter(name='backup-scheduled-task').delete()

    def test_get_schedule_settings_defaults(self):
        """Test that get_schedule_settings returns defaults when no settings exist"""
        from . import scheduler

        settings = scheduler.get_schedule_settings()

        self.assertEqual(settings['enabled'], False)
        self.assertEqual(settings['frequency'], 'daily')
        self.assertEqual(settings['time'], '03:00')
        self.assertEqual(settings['day_of_week'], 0)
        self.assertEqual(settings['retention_count'], 0)
        self.assertEqual(settings['cron_expression'], '')

    def test_update_schedule_settings_stores_values(self):
        """Test that update_schedule_settings stores values correctly"""
        from . import scheduler

        result = scheduler.update_schedule_settings({
            'enabled': True,
            'frequency': 'weekly',
            'time': '04:30',
            'day_of_week': 3,
            'retention_count': 7,
        })

        self.assertEqual(result['enabled'], True)
        self.assertEqual(result['frequency'], 'weekly')
        self.assertEqual(result['time'], '04:30')
        self.assertEqual(result['day_of_week'], 3)
        self.assertEqual(result['retention_count'], 7)

        # Verify persistence
        settings = scheduler.get_schedule_settings()
        self.assertEqual(settings['enabled'], True)
        self.assertEqual(settings['frequency'], 'weekly')

    def test_update_schedule_settings_invalid_frequency(self):
        """Test that invalid frequency raises ValueError"""
        from . import scheduler

        with self.assertRaises(ValueError) as context:
            scheduler.update_schedule_settings({'frequency': 'monthly'})

        self.assertIn('frequency', str(context.exception).lower())

    def test_update_schedule_settings_invalid_time(self):
        """Test that invalid time raises ValueError"""
        from . import scheduler

        with self.assertRaises(ValueError) as context:
            scheduler.update_schedule_settings({'time': 'invalid'})

        self.assertIn('HH:MM', str(context.exception))

    def test_update_schedule_settings_invalid_day_of_week(self):
        """Test that invalid day_of_week raises ValueError"""
        from . import scheduler

        with self.assertRaises(ValueError) as context:
            scheduler.update_schedule_settings({'day_of_week': 7})

        self.assertIn('day_of_week', str(context.exception).lower())

    def test_update_schedule_settings_invalid_retention(self):
        """Test that negative retention_count raises ValueError"""
        from . import scheduler

        with self.assertRaises(ValueError) as context:
            scheduler.update_schedule_settings({'retention_count': -1})

        self.assertIn('retention_count', str(context.exception).lower())

    def test_sync_creates_periodic_task_when_enabled(self):
        """Test that enabling schedule creates a PeriodicTask"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask

        scheduler.update_schedule_settings({
            'enabled': True,
            'frequency': 'daily',
            'time': '05:00',
        })

        task = PeriodicTask.objects.get(name='backup-scheduled-task')
        self.assertTrue(task.enabled)
        self.assertEqual(task.crontab.hour, '05')
        self.assertEqual(task.crontab.minute, '00')

    def test_sync_deletes_periodic_task_when_disabled(self):
        """Test that disabling schedule removes PeriodicTask"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask

        # First enable
        scheduler.update_schedule_settings({
            'enabled': True,
            'frequency': 'daily',
            'time': '05:00',
        })

        self.assertTrue(PeriodicTask.objects.filter(name='backup-scheduled-task').exists())

        # Then disable
        scheduler.update_schedule_settings({'enabled': False})

        self.assertFalse(PeriodicTask.objects.filter(name='backup-scheduled-task').exists())

    def test_weekly_schedule_sets_day_of_week(self):
        """Test that weekly schedule sets correct day_of_week in crontab"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask

        scheduler.update_schedule_settings({
            'enabled': True,
            'frequency': 'weekly',
            'time': '06:00',
            'day_of_week': 3,  # Wednesday
        })

        task = PeriodicTask.objects.get(name='backup-scheduled-task')
        self.assertEqual(task.crontab.day_of_week, '3')

    def test_cron_expression_stores_value(self):
        """Test that cron_expression is stored and retrieved correctly"""
        from . import scheduler

        result = scheduler.update_schedule_settings({
            'enabled': True,
            'cron_expression': '*/5 * * * *',
        })

        self.assertEqual(result['cron_expression'], '*/5 * * * *')

        # Verify persistence
        settings = scheduler.get_schedule_settings()
        self.assertEqual(settings['cron_expression'], '*/5 * * * *')

    def test_cron_expression_creates_correct_schedule(self):
        """Test that cron expression creates correct CrontabSchedule"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask

        scheduler.update_schedule_settings({
            'enabled': True,
            'cron_expression': '*/15 2 * * 1-5',  # Every 15 mins during 2 AM hour on weekdays
        })

        task = PeriodicTask.objects.get(name='backup-scheduled-task')
        self.assertEqual(task.crontab.minute, '*/15')
        self.assertEqual(task.crontab.hour, '2')
        self.assertEqual(task.crontab.day_of_month, '*')
        self.assertEqual(task.crontab.month_of_year, '*')
        self.assertEqual(task.crontab.day_of_week, '1-5')

    def test_cron_expression_invalid_format(self):
        """Test that invalid cron expression raises ValueError"""
        from . import scheduler

        # Too few parts
        with self.assertRaises(ValueError) as context:
            scheduler.update_schedule_settings({
                'enabled': True,
                'cron_expression': '0 3 *',
            })
        self.assertIn('5 parts', str(context.exception))

    def test_cron_expression_empty_uses_simple_mode(self):
        """Test that empty cron_expression falls back to simple frequency mode"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask

        scheduler.update_schedule_settings({
            'enabled': True,
            'frequency': 'daily',
            'time': '04:00',
            'cron_expression': '',  # Empty, should use simple mode
        })

        task = PeriodicTask.objects.get(name='backup-scheduled-task')
        self.assertEqual(task.crontab.minute, '00')
        self.assertEqual(task.crontab.hour, '04')
        self.assertEqual(task.crontab.day_of_week, '*')

    def test_cron_expression_overrides_simple_settings(self):
        """Test that cron_expression takes precedence over frequency/time"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask

        scheduler.update_schedule_settings({
            'enabled': True,
            'frequency': 'daily',
            'time': '03:00',
            'cron_expression': '0 */6 * * *',  # Every 6 hours (should override daily at 3 AM)
        })

        task = PeriodicTask.objects.get(name='backup-scheduled-task')
        self.assertEqual(task.crontab.minute, '0')
        self.assertEqual(task.crontab.hour, '*/6')
        self.assertEqual(task.crontab.day_of_week, '*')

    def test_periodic_task_uses_system_timezone(self):
        """Test that CrontabSchedule is created with the system timezone"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask
        from core.models import CoreSettings

        original_tz = CoreSettings.get_system_time_zone()

        try:
            # Set a non-UTC timezone
            CoreSettings.set_system_time_zone('America/New_York')

            scheduler.update_schedule_settings({
                'enabled': True,
                'frequency': 'daily',
                'time': '03:00',
            })

            task = PeriodicTask.objects.get(name='backup-scheduled-task')
            self.assertEqual(str(task.crontab.timezone), 'America/New_York')
        finally:
            scheduler.update_schedule_settings({'enabled': False})
            CoreSettings.set_system_time_zone(original_tz)

    def test_periodic_task_timezone_updates_with_schedule(self):
        """Test that CrontabSchedule timezone is updated when schedule is modified"""
        from . import scheduler
        from django_celery_beat.models import PeriodicTask
        from core.models import CoreSettings

        original_tz = CoreSettings.get_system_time_zone()

        try:
            # Create initial schedule with one timezone
            CoreSettings.set_system_time_zone('America/Los_Angeles')
            scheduler.update_schedule_settings({
                'enabled': True,
                'frequency': 'daily',
                'time': '02:00',
            })

            task = PeriodicTask.objects.get(name='backup-scheduled-task')
            self.assertEqual(str(task.crontab.timezone), 'America/Los_Angeles')

            # Change system timezone and update schedule
            CoreSettings.set_system_time_zone('Europe/London')
            scheduler.update_schedule_settings({
                'enabled': True,
                'time': '04:00',
            })

            task.refresh_from_db()
            self.assertEqual(str(task.crontab.timezone), 'Europe/London')
        finally:
            scheduler.update_schedule_settings({'enabled': False})
            CoreSettings.set_system_time_zone(original_tz)


class BackupTasksTestCase(TestCase):
    """Test cases for backup Celery tasks"""

    def setUp(self):
        self.temp_backup_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if Path(self.temp_backup_dir).exists():
            shutil.rmtree(self.temp_backup_dir)

    @patch('apps.backups.tasks.services.list_backups')
    @patch('apps.backups.tasks.services.delete_backup')
    def test_cleanup_old_backups_keeps_recent(self, mock_delete, mock_list):
        """Test that cleanup keeps the most recent backups"""
        from .tasks import _cleanup_old_backups

        mock_list.return_value = [
            {'name': 'backup-3.zip'},  # newest
            {'name': 'backup-2.zip'},
            {'name': 'backup-1.zip'},  # oldest
        ]

        deleted = _cleanup_old_backups(retention_count=2)

        self.assertEqual(deleted, 1)
        mock_delete.assert_called_once_with('backup-1.zip')

    @patch('apps.backups.tasks.services.list_backups')
    @patch('apps.backups.tasks.services.delete_backup')
    def test_cleanup_old_backups_does_nothing_when_under_limit(self, mock_delete, mock_list):
        """Test that cleanup does nothing when under retention limit"""
        from .tasks import _cleanup_old_backups

        mock_list.return_value = [
            {'name': 'backup-2.zip'},
            {'name': 'backup-1.zip'},
        ]

        deleted = _cleanup_old_backups(retention_count=5)

        self.assertEqual(deleted, 0)
        mock_delete.assert_not_called()

    @patch('apps.backups.tasks.services.list_backups')
    @patch('apps.backups.tasks.services.delete_backup')
    def test_cleanup_old_backups_zero_retention_keeps_all(self, mock_delete, mock_list):
        """Test that retention_count=0 keeps all backups"""
        from .tasks import _cleanup_old_backups

        mock_list.return_value = [
            {'name': 'backup-3.zip'},
            {'name': 'backup-2.zip'},
            {'name': 'backup-1.zip'},
        ]

        deleted = _cleanup_old_backups(retention_count=0)

        self.assertEqual(deleted, 0)
        mock_delete.assert_not_called()

    @patch('apps.backups.tasks.services.create_backup')
    @patch('apps.backups.tasks._cleanup_old_backups')
    def test_scheduled_backup_task_success(self, mock_cleanup, mock_create):
        """Test scheduled backup task success"""
        from .tasks import scheduled_backup_task

        mock_backup_file = MagicMock()
        mock_backup_file.name = 'scheduled-backup.zip'
        mock_backup_file.stat.return_value.st_size = 1024
        mock_create.return_value = mock_backup_file
        mock_cleanup.return_value = 2

        result = scheduled_backup_task(retention_count=5)

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['filename'], 'scheduled-backup.zip')
        self.assertEqual(result['size'], 1024)
        self.assertEqual(result['deleted_count'], 2)
        mock_cleanup.assert_called_once_with(5)

    @patch('apps.backups.tasks.services.create_backup')
    @patch('apps.backups.tasks._cleanup_old_backups')
    def test_scheduled_backup_task_no_cleanup_when_retention_zero(self, mock_cleanup, mock_create):
        """Test scheduled backup skips cleanup when retention is 0"""
        from .tasks import scheduled_backup_task

        mock_backup_file = MagicMock()
        mock_backup_file.name = 'scheduled-backup.zip'
        mock_backup_file.stat.return_value.st_size = 1024
        mock_create.return_value = mock_backup_file

        result = scheduled_backup_task(retention_count=0)

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['deleted_count'], 0)
        mock_cleanup.assert_not_called()

    @patch('apps.backups.tasks.services.create_backup')
    def test_scheduled_backup_task_failure(self, mock_create):
        """Test scheduled backup task handles failure"""
        from .tasks import scheduled_backup_task

        mock_create.side_effect = Exception("Backup failed")

        result = scheduled_backup_task(retention_count=5)

        self.assertEqual(result['status'], 'failed')
        self.assertIn('Backup failed', result['error'])
