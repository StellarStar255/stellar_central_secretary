# Third-party components in the Windows desktop build

The Windows desktop window uses dynamically linked PySide6 / Qt and Qt WebEngine.
PySide6 and the included Qt modules are distributed under their applicable LGPL v3
terms. The package includes the component metadata and license files in the
PySide6, PySide6_Essentials, PySide6_Addons and shiboken6 metadata directories.
The application uses replaceable shared DLLs rather than a statically linked Qt.

Upstream source, licenses and build instructions:

- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/
- https://code.qt.io/cgit/qt/qtwebengine.git/
- https://doc.qt.io/qt-6/licensing.html

Qt WebEngine also contains Chromium and third-party components under their own
licenses. Their notices are included in the Qt WebEngine resources and upstream
Qt WebEngine source. The Stellar Secretary application code remains under its
repository's MIT license.
