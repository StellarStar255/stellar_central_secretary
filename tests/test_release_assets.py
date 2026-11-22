import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('release_helper',Path(__file__).resolve().parent.parent/'packaging/release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

class ReleaseAssetsTest(unittest.TestCase):
    def test_build_cleanup_only_selects_older_published_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for folder in ('build','dist'):
                (root/folder).mkdir()
            old=[root/'build/release-v0.1.9',root/'dist/release-v9']
            for path in [*old,root/'build/release-v0.1.10',root/'dist/release-v0.1.11',
                         root/'dist/release-v0.1.12',root/'build/ios-app-store']:
                path.mkdir()
            package=root/'dist/Stellar-Secretary-0.1.9-macos-arm64.dmg'
            package.touch()
            self.assertCountEqual(release.old_build_artifacts(root,'0.1.11',{'0.1.9','0.1.11','0.1.12'}),[*old,package])

    def test_uploaded_assets_must_match_expected_size_and_digest(self):
        expected={'app.dmg':{'size':42,'digest':'sha256:'+'a'*64}}
        value={'assets':[{'name':'app.dmg','state':'uploaded',**expected['app.dmg']}]}
        release.verify_assets(value,expected)
        for field,changed in [('state','new'),('size',41),('digest','sha256:'+'b'*64)]:
            with self.subTest(field=field):
                altered={'assets':[{**value['assets'][0],field:changed}]}
                with self.assertRaises(RuntimeError):release.verify_assets(altered,expected)
    def test_missing_or_extra_asset_fails(self):
        with self.assertRaises(RuntimeError):release.verify_assets({'assets':[]},{'app.dmg':{'size':1}})
    def test_manifest_rejects_duplicates_and_invalid_hashes(self):
        line='a'*64+'  app.dmg\n'
        self.assertEqual(release.manifest_entries(line),{'app.dmg':'a'*64})
        for text in (line+line,'oops app.dmg','a'*64+'  ../secret'):
            with self.assertRaises(RuntimeError):release.manifest_entries(text)
