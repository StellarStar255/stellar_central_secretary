import io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from secretary import extension_install

class ExtensionInstallTest(unittest.TestCase):
    def test_installed_layout_exports_stable_folder_and_updates_in_place(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=root/'Example.app/Contents/Resources/browser-extension';source.mkdir(parents=True)
            (source/'manifest.json').write_text(json.dumps({'manifest_version':3,'version':'1.0','action':{'default_popup':'popup.html'}}));(source/'popup.html').write_text('Synthetic popup')
            data=root/'Library/Application Support/Fixture'
            first=extension_install.prepare(data,source);self.assertEqual(first['path'],str((data/'browser-extension').resolve()));self.assertTrue(first['updated'])
            again=extension_install.prepare(data,source);self.assertFalse(again['updated'])
            (source/'popup.html').write_text('Updated popup');last=extension_install.prepare(data,source)
            self.assertEqual(last['path'],first['path']);self.assertTrue(last['updated']);self.assertEqual((Path(last['path'])/'popup.html').read_text(),'Updated popup')
            self.assertEqual((source/'popup.html').read_text(),'Updated popup')
    def test_zip_contains_loadable_manifest_and_only_bundled_files(self):
        with zipfile.ZipFile(io.BytesIO(extension_install.download())) as archive:
            names=archive.namelist();self.assertIn('Stellar-Capture-Extension/manifest.json',names)
            manifest=json.loads(archive.read('Stellar-Capture-Extension/manifest.json'));self.assertEqual(manifest['manifest_version'],3)
            self.assertIn('Stellar-Capture-Extension/'+manifest['action']['default_popup'],names)
            self.assertFalse(any('..' in Path(name).parts for name in names))
    def test_export_refuses_symlink_destination(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)/'data';outside=Path(root)/'outside';data.mkdir();outside.mkdir()
            (data/'browser-extension').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):extension_install.prepare(data)
            self.assertEqual(list(outside.iterdir()),[])
    def test_open_folder_only_opens_the_prepared_directory(self):
        with tempfile.TemporaryDirectory() as root,patch.object(extension_install.sys,'platform','darwin'),patch.object(extension_install.subprocess,'run') as launch:
            result=extension_install.open_folder(root);self.assertTrue((Path(result['path'])/'manifest.json').is_file());self.assertEqual(launch.call_args.args[0],['/usr/bin/open',result['path']])
    def test_missing_bundle_does_not_create_empty_install_folder(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            with self.assertRaises(ValueError):extension_install.prepare(root/'data',root/'missing')
            self.assertFalse((root/'data/browser-extension').exists())
