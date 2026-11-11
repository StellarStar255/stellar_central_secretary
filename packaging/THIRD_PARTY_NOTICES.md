# Third-party components

HEIC/HEIF image decoding uses pillow-heif and its dynamically linked libheif
and codec libraries. Their licenses and bundled third-party notices are included
in pillow_heif distribution metadata. Upstream: https://github.com/bigcat88/pillow_heif

The Windows and Linux desktop window uses dynamically linked PySide6 / Qt and Qt WebEngine.
PySide6 and the included Qt modules are distributed under their applicable LGPL v3
terms. The package includes the component metadata and license files in the
PySide6, PySide6_Essentials, PySide6_Addons and shiboken6 metadata directories.
The application uses replaceable shared libraries rather than a statically linked Qt.

Upstream source, licenses and build instructions:

- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/
- https://code.qt.io/cgit/qt/qtwebengine.git/
- https://doc.qt.io/qt-6/licensing.html

Qt WebEngine also contains Chromium and third-party components under their own
licenses. Their notices are included in the Qt WebEngine resources and upstream
Qt WebEngine source. The Stellar Secretary application code remains under its
repository's MIT license.

PDF attachment thumbnails use pypdfium2 and its PDFium shared library. Their license and third-party notice files are included in the bundled pypdfium2 distribution metadata. Upstream: https://github.com/pypdfium2-team/pypdfium2

In-app Windows and Linux video playback uses dynamically linked Qt Multimedia and its FFmpeg media backend. Applicable component licenses and notices ship with Qt. Sources and build instructions: https://code.qt.io/cgit/qt/qtmultimedia.git/ and https://ffmpeg.org/download.html .
