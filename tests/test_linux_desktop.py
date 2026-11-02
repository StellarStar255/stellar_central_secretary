import io,json,os,tarfile,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,patch
from secretary import launcher,linux_update,paths,system_integration,updater
from secretary.server import Service


class LinuxDesktopTest(unittest.TestCase):
    def test_graphical_session_selection_preserves_headless_use(self):
        self.assertFalse(launcher.desktop_session('linux',{}))
        self.assertTrue(launcher.desktop_session('linux',{'DISPLAY':':1'}))
        self.assertTrue(launcher.desktop_session('linux',{'WAYLAND_DISPLAY':'wayland-0'}))
        self.assertTrue(launcher.desktop_session('win32',{}))

    def test_external_system_programs_do_not_inherit_bundle_libraries(self):
        source={'LD_LIBRARY_PATH':'/bundle/_internal:/original','LD_LIBRARY_PATH_ORIG':'/original','QT_PLUGIN_PATH':'/bundle/_internal/plugins','QT_QPA_PLATFORM_PLUGIN_PATH':'/system/plugins'}
        with patch.object(system_integration.sys,'platform','linux'),patch.object(system_integration.sys,'frozen',True,create=True),patch.object(system_integration.sys,'_MEIPASS','/bundle/_internal',create=True):
            clean=system_integration.external_env(source)
        self.assertEqual(clean['LD_LIBRARY_PATH'],'/original');self.assertNotIn('QT_PLUGIN_PATH',clean)
        self.assertEqual(clean['QT_QPA_PLATFORM_PLUGIN_PATH'],'/system/plugins');self.assertIn('/bundle',source['LD_LIBRARY_PATH'])

    def test_linux_host_exposes_mode_panels_dock_and_lease(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);owner=uuid.uuid4().hex
            try:
                metadata={'platform':'linux','mode':'desktop','state':'ready','tray':True,'dock':True,'window_visible':True,'window_loaded':True,'window_id':123,'browser_opens':0}
                service.desktop_heartbeat({'owner':owner,'desktop':metadata})
                self.assertEqual(service.desktop_status()['platform'],'linux');self.assertTrue(service.desktop_status()['dock'])
                service.switch_interface('browser','settings');self.assertEqual(service.interface_request['panel'],'settings')
                with self.assertRaises(ValueError):service.switch_interface('desktop','unexpected')
                self.assertEqual(service.archive.settings()['interface_mode'],'browser')
            finally:service.close()

    def test_linux_updates_select_the_matching_distribution(self):
        with patch.object(updater,'MAC',False),patch.object(updater,'WINDOWS',False),patch.object(updater.sys,'platform','linux'),patch.object(updater.platform,'machine',return_value='x86_64'),patch.object(paths,'FROZEN',True):
            self.assertTrue(updater.supported())
            for kind,suffix in [('deb','.deb'),('portable','.tar.gz')]:
                with patch.object(linux_update,'install_kind',return_value=kind):
                    self.assertIsNotNone(updater._asset_pattern().search('Stellar-Secretary-99.0.0-linux-x64'+suffix))
                    self.assertIsNone(updater._asset_pattern().search('Stellar-Secretary-99.0.0-windows-x64-setup.exe'))

    def test_cancelled_debian_authorization_keeps_application_running(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            with patch.object(linux_update,'install_kind',return_value='deb'),patch.object(linux_update.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(linux_update.subprocess,'run',return_value=Mock(returncode=126,stdout='',stderr='cancelled')),patch.object(paths,'DATA_DIR',root),patch.object(linux_update,'_relaunch') as relaunch:
                with self.assertRaisesRegex(RuntimeError,'授权已取消'):linux_update.install(root/'fixture.deb',root,'0'*64,'99.0.0')
                relaunch.assert_not_called()

    def test_successful_debian_install_uses_verified_privileged_copy_then_relaunches(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            with patch.object(linux_update,'install_kind',return_value='deb'),patch.object(linux_update.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(linux_update.subprocess,'run',return_value=Mock(returncode=0,stdout='OK',stderr='')) as run,patch.object(paths,'DATA_DIR',root),patch.object(linux_update,'_relaunch') as relaunch:
                self.assertTrue(linux_update.install(root/'fixture.deb',root,'a'*64,'99.0.0'))
                self.assertIn('sha256sum --check',run.call_args.args[0][3]);self.assertEqual(run.call_args.args[0][-2:],['a'*64,'99.0.0'])
                relaunch.assert_called_once_with(root)

    def test_portable_update_stages_complete_tree_and_rejects_unsafe_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);current=root/'current';current.mkdir();(current/'_internal').mkdir();(current/'Stellar Secretary').write_bytes(b'old')
            archive=root/'update.tar.gz'
            def make(name='Stellar-Secretary/Stellar Secretary'):
                with tarfile.open(archive,'w:gz') as out:
                    directory=tarfile.TarInfo('Stellar-Secretary/_internal');directory.type=tarfile.DIRTYPE;out.addfile(directory)
                    for path in (name,'Stellar-Secretary/start.sh'):
                        info=tarfile.TarInfo(path);info.mode=0o755;info.size=3;out.addfile(info,io.BytesIO(b'new'))
            make()
            with patch.object(linux_update.shutil,'which',return_value='python3'):
                stage,new=linux_update.prepare_portable(archive,current,root/'data');self.assertEqual((new/'Stellar Secretary').read_bytes(),b'new')
                linux_update.shutil.rmtree(stage)
                with self.assertRaises(linux_update.ManualInstall):linux_update.prepare_portable(archive,current,current/'data')
                make('../escape')
                with self.assertRaises(ValueError):linux_update.prepare_portable(archive,current,root/'data')
            self.assertEqual((current/'Stellar Secretary').read_bytes(),b'old');self.assertFalse((root/'escape').exists())
