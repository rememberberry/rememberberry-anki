import os
import json
import random
from functools import partial
from aqt import mw
from aqt.utils import showInfo
from aqt.qt import *
from anki.utils import ids2str, fieldChecksum, stripHTML, \
    intTime, splitFields, joinFields, maxID, json, devMode

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
            self.config = {'version': 1,
                           'sentence_decks': [],
                           'active_vocabulary_decks': [],
                           'known_vocabulary_decks': [], 
                           'added': []}

    @classmethod
    def config_filename(cls):
        user_files = os.path.join(os.path.dirname(__file__), 'user_files')
        try:
            os.makedirs(user_files)
        except:
            pass
        return os.path.join(user_files, '%s_config.json' % mw.pm.name)

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
        self.max_num_results = 500
        self.min_difficulty = 0
        self.max_difficulty = 30
        self.curr_difficulty = 10
        self.num_columns = 4
        self.editor = editor

        def _close(orig_self, orig_close):
            self.close()
            orig_close(orig_self)

        editor.parentWindow.closeEvent = partial(_close, orig_close=editor.parentWindow.closeEvent)
        editor.mw.closeEvent = partial(_close, orig_close=editor.mw.closeEvent)
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
        self.search_button = QPushButton('Search')
        self.search_button.clicked.connect(self.search)

        self.difficulty_slider = QSlider(Qt.Horizontal)
        self.difficulty_slider.setFocusPolicy(Qt.StrongFocus)
        self.difficulty_slider.setTickPosition(QSlider.TicksBothSides)
        self.difficulty_slider.setTickInterval(1)
        self.difficulty_slider.setMinimum(self.min_difficulty)
        self.difficulty_slider.setMaximum(self.max_difficulty)
        self.difficulty_slider.setValue(self.curr_difficulty)
        self.difficulty_slider.setSingleStep(1)
        self.difficulty_slider.valueChanged.connect(self.difficulty_changed)

        self.filter_box = QLineEdit(self)
        self.filter_box.returnPressed.connect(self.search)

        self.find_tab.layout = QVBoxLayout(self)
        self.find_tab.setLayout(self.find_tab.layout)
        group = QGroupBox()
        group.layout = QGridLayout()
        group.setLayout(group.layout)
        group.layout.addWidget(self.difficulty_slider, 0, 0)
        group.layout.addWidget(self.filter_box, 0, 1)
        self.find_tab.layout.addWidget(group, 0)
        self.find_tab.layout.addWidget(self.search_button, 1)
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(self.num_columns)
        self.table_widget.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)

        self.table_widget.hide()
        self.find_tab.layout.addWidget(self.table_widget, 2)

        button_group = QGroupBox()
        button_group.layout = QGridLayout()
        button_group.setLayout(button_group.layout)
        add_button = QPushButton('Add Cards')
        add_button.clicked.connect(self.add)
        add_cloze_button = QPushButton('Add as Cloze')
        add_cloze_button.clicked.connect(self.add_cloze)
        close_button = QPushButton('Close')
        close_button.clicked.connect(self.close)
        button_group.layout.addWidget(add_button, 0, 0)
        button_group.layout.addWidget(add_cloze_button, 0, 1)
        button_group.layout.addWidget(close_button, 0, 2)
        button_group.setFixedHeight(50)
        button_group.setFixedWidth(400)
        add_button.setFixedWidth(110)
        add_cloze_button.setFixedWidth(110)
        close_button.setFixedWidth(110)
        self.find_tab.layout.addStretch()
        self.find_tab.layout.addWidget(button_group, 3)

        self.search_button.setFixedWidth(110)
        self.difficulty_slider.setFixedWidth(300)
        self.filter_box.setFixedWidth(300)

    def add(self):
        target_did = self.editor.parentWindow.deckChooser.selectedId()
        note_ids = []
        for row in self.table_widget.selectionModel().selectedRows():
            (_, nid, *_), *_ = self.search_results[row.row()]
            notes = mw.col.db.all('select * from notes where id = %i' % nid)
            note_ids.append(nid)

        note_ids_str = ', '.join([str(n) for n in note_ids])
        cards = mw.col.db.all('select * from cards where nid in (%s)' % note_ids_str)
        for card in cards:
            # Create a new card id
            new_card = (maxID(mw.col.db), card[1], target_did, *card[3:])

            templ_str = ','.join(['?']*len(new_card))
            insert_query = 'insert into cards values (%s)' % templ_str
            mw.col.db.execute(insert_query, *new_card)

        showInfo('Added %i cards from %s notes' % (len(cards), len(note_ids)))

    def add_cloze(self):
        pass

    def difficulty_changed(self):
        self.curr_difficulty = self.difficulty_slider.value()

    def search(self):
        filter_text = self.filter_box.text()
        self.table_widget.clear()
        self.do_the_thing(None if filter_text == '' else filter_text)
        for i in range(self.num_columns):
            self.table_widget.setHorizontalHeaderItem(i, QTableWidgetItem('Field %s' % (i+1)));
            self.table_widget.setColumnWidth(i, 300)

        sentences = sorted([s for s in self.sentences if self.curr_difficulty < s[-1] < self.max_difficulty],
                           key=lambda x: x[-1])
        self.search_results = sentences[:self.max_num_results]
        self.table_widget.setRowCount(len(self.search_results))

        for i, (nid, field_idx, fields, strengths, difficulty) in enumerate(self.search_results):
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
                self.table_widget.setCellWidget(i, j+1, QLabel(fields[k]))
                if j >= self.num_columns-1:
                    break
            self.table_widget.setCellWidget(i, self.num_columns-1, QLabel(str(difficulty)))
        self.table_widget.resizeRowsToContents()
        self.table_widget.resizeColumnsToContents()
        self.table_widget.show()

    def do_the_thing(self, filter_text=None):
        self.read_config()
        decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        known_decks = self.config['known_vocabulary_decks']
        active_decks = self.config['active_vocabulary_decks']
        sentence_decks = self.config['sentence_decks']
        user_decks = (list(zip(known_decks, [True]*len(known_decks))) +
                      list(zip(active_decks, [False]*len(active_decks))))
        vocab_strengths = defaultdict(list)

        def _iter_note_hanzi(deck_name):
            did = self.get_did_from_name(deck_name, decks)
            if did is None:
                return
            cards = mw.col.db.all("select nid, max(reps-lapses) from cards where did=%s group by nid" % did)
            ids_str = ', '.join(str(nid) for nid, _ in cards)
            note_fields = mw.col.db.all("select id, flds from notes where id in (%s)" % ids_str)
            note_fields = {nid: fields.split('\x1f') for nid, fields in note_fields}
            for nid, reps_min_lapses in cards:
                fields = note_fields[nid]
                for i, field in enumerate(fields):
                    if len(filter_text_hanzi(field)) == 0:
                        continue
                    yield nid, reps_min_lapses, i, fields

        for deck_name, is_known in user_decks:
            for nid, reps_min_lapses, field_idx, fields in _iter_note_hanzi(deck_name):
                for word in split_hanzi(fields[field_idx]):
                    vocab_strengths[word].append(1.0 if is_known else
                                                 min((reps_min_lapses) / 10, 1.0))

        # Build a map from first character to full words
        char_to_words = defaultdict(list)
        for word in vocab_strengths.keys():
            char_to_words[word[0]].append(word)
        # Sort the word lists so we always check longest word first
        for key, words in char_to_words.items():
            char_to_words[key] = sorted(words, key=lambda x: len(x), reverse=True)

        # Go through sentence decks, collect statistics
        sentences = []
        for deck_name in sentence_decks:
            for nid, reps_min_lapses, field_idx, fields in _iter_note_hanzi(deck_name):
                field = fields[field_idx]
                if filter_text is not None and filter_text not in field:
                    continue
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
                        strength = min(1.0, sum(vocab_strengths[word]))
                        strengths.append((curr_idx, curr_idx+len(word), strength))
                        # -1 because it'll be incremented right after
                        curr_idx += len(word) - 1
                        break
                    curr_idx += 1
                difficulty = sum(10*(1-s[-1]) for s in strengths if s[-1] >= 0)
                sentences.append((nid, field_idx, fields, strengths, difficulty))

        self.sentences = sentences

    def get_target_deck(self):
        return self.editor.parentWindow.deckChooser.selectedId()
