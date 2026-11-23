"""Offer recovery before the Windows desktop service opens a library."""
import sys
from pathlib import Path

from .i18n import translate

_app = None

def choose(problem):
    global _app
    from .desktop_qt import configure_rendering
    configure_rendering()
    from PySide6.QtCore import QLocale, Qt
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    # Import WebEngine before creating the app, just as the normal launcher does.
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    _app = QApplication.instance() or QApplication([sys.argv[0]])
    _app.setQuitOnLastWindowClosed(False)
    language = 'zh' if QLocale.system().language() == QLocale.Language.Chinese else 'en'

    def tr(value):
        return translate(value, language)

    while True:
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr('恢复记忆目录'))
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(tr(problem.reason) + '\n' + str(problem.root))
        box.setInformativeText(tr('可重试原目录或选择已有知识库。也可以选择空文件夹新建知识库，今后直接打开新库。'))
        retry = box.addButton(tr('重试原目录'), QMessageBox.ButtonRole.AcceptRole)
        locate = box.addButton(tr('选择已有知识库…'), QMessageBox.ButtonRole.ActionRole)
        create = box.addButton(tr('新建知识库…'), QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton(tr('退出程序'), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(retry)
        box.setEscapeButton(cancel)
        box.exec()
        selected = box.clickedButton()
        if selected == retry:
            return 'retry', None
        if selected not in (locate, create):
            return None
        creating = selected == create
        title = tr('为新知识库选择空文件夹' if creating else '选择已有知识库…')
        folder = QFileDialog.getExistingDirectory(None, title, str(Path.home()))
        if folder:
            return ('new' if creating else 'existing'), folder
