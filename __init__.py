from aqt import mw
from aqt.utils import showInfo
from aqt.qt import *
from anki.hooks import addHook

#from aqt.toolbar import Toolbar
from rememberberry.widget import RememberberryWidget
import aqt.toolbar

def _rememberberryLinkHandler(editor):
    widget = RememberberryWidget(editor)
    mw.rememberberry = widget
    widget.show()


def _centerLinks(self):
    links = [
        ["decks", _("Decks"), _("Shortcut key: %s") % "D"],
        ["add", _("Add"), _("Shortcut key: %s") % "A"],
        ["browse", _("Browse"), _("Shortcut key: %s") % "B"],
        ["stats", _("Stats"), _("Shortcut key: %s") % "Shift+S"],
        ["sync", _("Sync"), _("Shortcut key: %s") % "Y"],
        ["rchinese", _("RChinese"), _("Shortcut key: %s") % "R"]
    ]
    #links = [
        #["decks", _("Decks"), _("Shortcut key: %s") % "D"],
        #["add", _("Add"), _("Shortcut key: %s") % "A"],
        #["browse", _("Browse"), _("Shortcut key: %s") % "B"],
        #["rememberberry", _("Rememberberry"), _("Shortcut key: %s") % "R"]
    #]

    showInfo('test2')
    self.link_handlers["rchinese"] = _rememberberryLinkHandler

    return self._linkHTML(links)

#showInfo(str(aqt.toolbar.Toolbar._centerLinks))
#aqt.toolbar.Toolbar._centerLinks = _centerLinks
#showInfo(str(aqt.toolbar.Toolbar._centerLinks))


def addMyButton(buttons, editor):
    editor._links['rememberberry'] = _rememberberryLinkHandler
    return buttons + [editor._addButton(
        "iconname", # "/full/path/to/icon.png",
        "rememberberry", # link name
        "tooltip")]

addHook("setupEditorButtons", addMyButton)
