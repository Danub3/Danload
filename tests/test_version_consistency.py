import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def extract(pattern, path):
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text)
    if not match:
        raise AssertionError(f"Version pattern not found in {path.name}")
    return match.group(1)


class VersionConsistencyTests(unittest.TestCase):
    def test_public_versions_match_application_version(self):
        app_version = extract(r'APP_VERSION\s*=\s*"([^"]+)"', ROOT / "app.py")
        installer_version = extract(
            r'#define MyAppVersion\s+"([^"]+)"', ROOT / "installer.iss"
        )
        file_version = extract(
            r"StringStruct\(u'FileVersion', u'([^']+)'\)",
            ROOT / "assets" / "windows_version_info.txt",
        )
        product_version = extract(
            r"StringStruct\(u'ProductVersion', u'([^']+)'\)",
            ROOT / "assets" / "windows_version_info.txt",
        )

        self.assertEqual(installer_version, app_version)
        self.assertEqual(file_version, app_version)
        self.assertEqual(product_version, app_version)

    def test_fixed_pe_version_uses_required_four_part_tuple(self):
        app_version = extract(r'APP_VERSION\s*=\s*"([^"]+)"', ROOT / "app.py")
        fixed_version = extract(
            r"filevers=\(([^)]+)\)", ROOT / "assets" / "windows_version_info.txt"
        )
        actual = tuple(int(part.strip()) for part in fixed_version.split(","))
        expected = tuple(int(part) for part in app_version.split(".")) + (0,)

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
