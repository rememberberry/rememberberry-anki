import os
import json
from aqt import mw
from aqt.utils import showInfo
from aqt.qt import *

from .han import filter_text_hanzi

class ConfigWidget(QWidget):
    def __init__(self):
        QWidget.__init__(self)

    def read_config(self):
        try:
            with open(self.config_filename(), 'r') as f:
                self.config = json.loads(f.read())
        except:
            self.config = {'sentence_decks': [],
                           'active_vocabulary_decks': [],
                           'known_vocabulary_decks': []}

    @classmethod
    def config_filename(cls):
        user_files = os.path.join(os.path.dirname(__file__), 'user_files')
        try:
            os.makedirs(user_files)
        except:
            pass
        return os.path.join(user_files, 'config.json')

    def write_config(self):
        with open(self.config_filename(), 'w') as f:
            f.write(json.dumps(self.config))


class DeckSingleChoice(ConfigWidget):
    def __init__(self, config_key):
        ConfigWidget.__init__(self)
        self.config_key = config_key
        self.initUI()

    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(5)
        self.combo_box = QComboBox(self)
        self.layout.addWidget(self.combo_box, 0)
        self.rebuildUI()

    def rebuildUI(self):
        try:
            self.combo_box.currentIndexChanged.disconnect(self.on_active_changed)
        except:
            pass
        self.read_config()
        self.combo_box.clear()
        decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        for i, (deck_id, deck_info) in enumerate(decks.items()):
            deck_name = deck_info['name']
            self.combo_box.addItem(deck_name)

        deck_name = self.config.get(self.config_key, None)
        index = self.combo_box.findText(deck_name, Qt.MatchFixedString)
        if index >= 0:
            self.combo_box.setCurrentIndex(index)
        self.combo_box.currentIndexChanged.connect(self.on_active_changed)


    @pyqtSlot()
    def on_active_changed(self):
        self.read_config()
        self.config[self.config_key] = self.combo_box.currentText()
        self.write_config()


class DeckMultipleChoice(ConfigWidget):
    def __init__(self, config_key):
        ConfigWidget.__init__(self)
        self.config_key = config_key
        self.first = True
        self.layout = None
        self.initUI()

    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(5)
        self.decks_list_widget = QListWidget(self)
        self.decks_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        self.layout.addWidget(self.decks_list_widget, 0)
        self.rebuildUI()

    def rebuildUI(self):
        self.read_config()
        try:
            self.decks_list_widget.itemSelectionChanged.disconnect(self.on_item_changed)
        except:
            pass
        self.decks_list_widget.clear()
        self.decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        for deck_id, deck_info in self.decks.items():
            deck_name = deck_info['name']
            item = QListWidgetItem()
            item.setText(deck_name)
            self.decks_list_widget.addItem(item)

        for deck_name in self.config[self.config_key]:
            items = self.decks_list_widget.findItems(deck_name, Qt.MatchExactly)
            for item in items:
                self.decks_list_widget.setCurrentIndex(self.decks_list_widget.indexFromItem(item))

        self.decks_list_widget.itemSelectionChanged.connect(self.on_item_changed)

    @pyqtSlot()
    def on_item_changed(self):
        self.read_config()
        self.config[self.config_key] = [str(item.text()) for item in self.decks_list_widget.selectedItems()]
        self.write_config()


class RememberberryWidget(ConfigWidget):
    def __init__(self):
        QWidget.__init__(self)
        self.build()

    def build(self):

        self.setWindowTitle('Rememberberry')
        self.layout = QVBoxLayout(self)
 
        # Initialize tab screen
        self.tabs = QTabWidget()
        self.find_tab = QWidget()	
        self.decks_tab = QWidget()
        self.tabs.resize(1000, 1200) 
 
        # Add tabs
        self.tabs.addTab(self.find_tab, 'Find')
        self.tabs.addTab(self.decks_tab, 'Decks')

        # Create find tab
        self.create_find_tab()
 
        # Create decks tab
        self.decks_tab.layout = QGridLayout(self)
        self.decks_tab.layout.setSpacing(5)
        self.sentence_deck_choice = DeckMultipleChoice('sentence_decks')
        self.decks_tab.layout.addWidget(QLabel('Decks to draw sentences from:', self), 0, 0)
        self.decks_tab.layout.addWidget(self.sentence_deck_choice, 1, 0)

        l1 = QLabel('Decks where you keep active vocab (and possibly sentences):', self); l1.setWordWrap(True)
        self.decks_tab.layout.addWidget(l1, 2, 0)
        self.active_vocabulary_deck_choice = DeckMultipleChoice('active_vocabulary_decks')
        self.decks_tab.layout.addWidget(self.active_vocabulary_deck_choice, 3, 0)
        l2 = QLabel(('Decks where you keep known vocab which is not active '
                    '(e.g. HSK decks). For example, if you are HSK level 4, '
                    'you can add HSK 1-3 here as "known" decks:'), self); l2.setWordWrap(True)
        self.decks_tab.layout.addWidget(l2, 4, 0)
        self.known_vocabulary_deck_choice = DeckMultipleChoice('known_vocabulary_decks')
        self.decks_tab.layout.addWidget(self.known_vocabulary_deck_choice, 5, 0)

        self.decks_tab.setLayout(self.decks_tab.layout)
        self.tabs.currentChanged.connect(self.on_tab_changed)
 
        # Add tabs to widget        
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)


    @pyqtSlot()
    def on_tab_changed(self):
        self.sentence_deck_choice.rebuildUI()
        self.active_vocabulary_deck_choice.rebuildUI()
        self.known_vocabulary_deck_choice.rebuildUI()

    def create_find_tab(self):
        self.read_config()
        decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        known = self.config['known_vocabulary_decks']
        active = self.config['active_vocabulary_decks']
        user_decks = (list(zip(known, [True]*len(known))) +
                      list(zip(active, [True]*len(active))))
        # Collect all the active and non-active vocab
        # Filter on hanzi unicode to find the right fields
        vocab = {} # { hanzi: memory strength / None(if "known")

        first = True
        for deck_name, is_known in user_decks:
            dids = [deck_id for (deck_id, deck_info) in decks.items()
                   if deck_info['name'] == deck_name]
            if len(dids) == 0:
                continue
            did = dids[0]
            notes = mw.col.db.all("select nid, reps, lapses from cards where did=%s" % did)
            note_fields = [mw.col.db.all("select flds from notes where id=%s" % nid)[0][0].split('\x1f')
                           for nid, _, _ in notes]
            for note, fields in zip(notes, note_fields):
                for field in fields:
                    if first:
                        #showInfo(field)
                        first = False
                    word = filter_text_hanzi(field)
                    if len(word) == 0:
                        continue
                    reps, lapses = note[1:]
                    vocab[word] = 1.0 if is_known else max((reps-lapses) / 10, 1.0)



        #showInfo(str(vocab.items()[:5]))

        # Go through sentence decks, collect statistics
        sentences = {} # { sentence: score = average memory strength per char }
