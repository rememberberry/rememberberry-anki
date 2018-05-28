from aqt import mw
from aqt.utils import showInfo
from aqt.qt import *
from anki.hooks import addHook

#from aqt.toolbar import Toolbar
from rememberberry.widget import RememberberryWidget
import aqt.toolbar

def _rememberberry_handler(editor):
    widget = RememberberryWidget(editor)
    mw.rememberberry = widget
    widget.show()


def add_rememberberry(buttons, editor):
    editor._links['rememberberry'] = _rememberberry_handler
    return buttons + [editor._addButton(
        "iconname", # "/full/path/to/icon.png",
        "rememberberry", # link name
        "tooltip")]

addHook("setupEditorButtons", add_rememberberry)
