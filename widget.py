import os
import json
import random
from aqt import mw
from aqt.utils import showInfo
from aqt.qt import *

from .han import filter_text_hanzi, is_hanzi, split_hanzi
from collections import defaultdict

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
    def __init__(self, editor):
        QWidget.__init__(self)
        self.editor = editor
        self.build()

    def build(self):

        self.setWindowTitle('Rememberberry')
        self.resize(1000, 800)
        self.layout = QVBoxLayout(self)
 
        # Initialize tab screen
        self.tabs = QTabWidget()
        self.find_tab = QWidget()	
        self.decks_tab = QWidget()
 
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

        l1 = QLabel('Decks where you keep active vocab and sentences:', self); l1.setWordWrap(True)
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

    def get_did_from_name(self, deck_name, decks):
        dids = [deck_id for (deck_id, deck_info) in decks.items()
               if deck_info['name'] == deck_name]
        if len(dids) == 0:
            return None
        return dids[0]

    def create_find_tab(self):
        self.do_the_thing()
        self.table_widget = QTableWidget()
        self.table_widget.setRowCount(10)
        num_columns = 4
        self.table_widget.setColumnCount(num_columns)
        for i in range(num_columns):
            self.table_widget.setHorizontalHeaderItem(i, QTableWidgetItem("Field %s" % (i+1)));
            self.table_widget.setColumnWidth(i, 300)
        self.find_tab.layout = QGridLayout(self)
        sample = random.sample(self.sentences, 20)
        for i, (field_idx, fields, strengths) in enumerate(sample):
            colors = []
            sentence = fields[field_idx]
            for start, end, s in strengths:
                if s < 0:
                    colors.append('white')
                elif 0 <= s < 0.2:
                    colors.append('red')
                elif 0.2 <= s < 0.4:
                    colors.append('yellow')
                elif 0.4 <= s < 0.6:
                    colors.append('lightgray')
                elif 0.6 <= s < 0.8:
                    colors.append('lightgreen')
                elif 0.8 <= s <= 1:
                    colors.append('green')

            label = ''.join('<span style="background: %s; border-color: black">%s</span><span> </span>'
                            % (color, sentence[start:end])
                            for color, (start, end, _) in zip(colors, strengths))

            self.table_widget.setCellWidget(i, 0, QLabel(label))
            for j, k in enumerate([k for k in range(len(fields)) if k != field_idx]):
                if j+1 >= num_columns:
                    break
                self.table_widget.setCellWidget(i, j+1, QLabel(fields[k]))

        self.find_tab.layout.addWidget(self.table_widget, 0, 0)
        self.find_tab.setLayout(self.find_tab.layout)

    def do_the_thing(self):
        self.read_config()
        decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        known_decks = self.config['known_vocabulary_decks']
        active_decks = self.config['active_vocabulary_decks']
        sentence_decks = self.config['sentence_decks']
        user_decks = (list(zip(known_decks, [True]*len(known_decks))) +
                      list(zip(active_decks, [False]*len(active_decks))))
        # Collect all the active and non-active vocab
        # Filter on hanzi unicode to find the right fields
        vocab_strength = defaultdict(lambda: 0)

        def _iter_note_hanzi(deck_name):
            did = self.get_did_from_name(deck_name, decks)
            if did is None:
                return
            cards = mw.col.db.all("select id, nid, reps, lapses from cards where did=%s" % did)
            ids_str = ', '.join(str(nid) for _, nid, *_ in cards)
            note_fields = mw.col.db.all("select flds from notes where id in (%s)" % ids_str)
            note_fields = [fields[0].split('\x1f') for fields in note_fields]
            for card, fields in zip(cards, note_fields):
                for i, field in enumerate(fields):
                    if len(filter_text_hanzi(field)) == 0:
                        continue
                    yield card, i, fields

        for deck_name, is_known in user_decks:
            for (*_, reps, lapses), field_idx, fields in _iter_note_hanzi(deck_name):
                for word in split_hanzi(fields[field_idx]):
                    strength = max(vocab_strength[word], 1.0 if is_known else
                                   min((reps-lapses) / 10, 1.0))

                    vocab_strength[word] = strength

        # Build a map from first character to full words
        char_to_words = defaultdict(list)
        for word in vocab_strength.keys():
            char_to_words[word[0]].append(word)
        # Sort the word lists so we always check longest word first
        for key, words in char_to_words.items():
            char_to_words[key] = sorted(words, key=lambda x: len(x), reverse=True)

        # Go through sentence decks, collect statistics
        sentences = []
        for deck_name in sentence_decks:
            for _, field_idx, fields in _iter_note_hanzi(deck_name):
                field = fields[field_idx]
                strengths = []
                words = []
                curr_idx = 0
                non_hanzi_start = -1
                while curr_idx < len(field):
                    curr_char = field[curr_idx]
                    if curr_char not in char_to_words:
                        if non_hanzi_start < 0:
                            non_hanzi_start = curr_idx
                        curr_idx += 1
                        continue

                    if non_hanzi_start >= 0:
                        strengths.append((non_hanzi_start, curr_idx, -1.0))
                        non_hanzi_start = -1

                    for word in char_to_words[curr_char]:
                        if field[curr_idx:curr_idx+len(word)] != word:
                            continue
                        strengths.append((curr_idx, curr_idx+len(word), vocab_strength[word]))
                        # -1 because it'll be incremented right after
                        curr_idx += len(word) - 1
                        break
                    curr_idx += 1
                sentences.append((field_idx, fields, strengths))

        self.sentences = sentences

    def get_target_deck(self):
        return self.editor.parentWindow.deckChooser.selectedId()
