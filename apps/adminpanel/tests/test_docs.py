from django.test import TestCase
from drf_yasg import openapi

from utils.api_docs import ApiSchemaGenerator


class AdminSchemaTests(TestCase):
    def test_admin_endpoints_are_documented(self):
        schema = ApiSchemaGenerator(openapi.Info(title='SafariChap API', default_version='v1')).get_schema(public=True)
        # Paths are relative to the common `/api` base path.
        admin_paths = [p for p in schema['paths'] if p.startswith('/admin/')]
        self.assertIn('/admin/me/', admin_paths)
        self.assertGreater(len(admin_paths), 40)
