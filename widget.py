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
from .cedict import load_cedict
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
                           'active_vocabulary_decks': []}

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
        self.redo_search = True
        file_dir = os.path.dirname(__file__)
        self.cedict = load_cedict(os.path.join(file_dir, 'corpus/sources/cedict_ts.u8'))

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
        self.settings_tab = QWidget()
 
        # Add tabs
        self.tabs.addTab(self.find_tab, 'Find')
        self.tabs.addTab(self.decks_tab, 'Decks')
        self.tabs.addTab(self.settings_tab, 'Settings')

        # Create find tab
        self.create_find_tab()
 
        # Create decks tab
        self.create_decks_tab()

        # Create settings tab
        self.create_settings_tab()

        self.tabs.currentChanged.connect(self.on_tab_changed)
 
        # Add tabs to widget        
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)

        self.filter_box.setFocus(True)


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

    def update_mark_items(self, mark_type):
        nids = [c[0] for c in mw.col.db.all('select nid from cards where data="%s"' % mark_type)]
        nids = set(nids)
        ids_str = ', '.join(str(nid) for nid in nids)
        note_fields = mw.col.db.all("select id, flds from notes where id in (%s)" % ids_str)
        note_fields = {nid: fields.split('\x1f') for nid, fields in note_fields}
        self.mark_notes[mark_type] = []
        for nid in nids:
            fields = note_fields[nid]
            hanzi = []
            for i, field in enumerate(fields):
                h = filter_text_hanzi(field)
                if len(h) > 0:
                    hanzi.append(h)
            self.mark_notes[mark_type].append((nid, '|'.join(hanzi)))

        model = QStandardItemModel()

        model.removeRows(0, model.rowCount())
        it = []
        model = QStandardItemModel()
        for _, label in self.mark_notes[mark_type]:
            item = QStandardItem(label)
            item.setCheckState(Qt.Unchecked)
            item.setCheckable(True)
            it.append(item)
            model.appendRow(item)

        self.mark_items[mark_type] = it
        self.mark_views[mark_type].setModel(model)

    def create_settings_tab(self):
        self.mark_notes, self.mark_items = {}, {}
        self.settings_tab.layout = QGridLayout(self)
        self.settings_tab.layout.addWidget(QLabel('Ignored:', self), 0, 0)
        self.settings_tab.layout.addWidget(QLabel('Known:', self), 0, 1)

        self.mark_views = {'ignore': QListView(), 'known': QListView()}
        self.settings_tab.layout.addWidget(self.mark_views['ignore'], 1, 0)
        self.settings_tab.layout.addWidget(self.mark_views['known'], 1, 1)

        self.update_mark_items('ignore')
        self.update_mark_items('known')

        def _remove(mark_type):
            remove_indices = set()
            for i, item in enumerate(self.mark_items[mark_type]):
                if item.checkState() != Qt.Checked:
                    continue
                remove_indices.add(i)
                nid, _ = self.mark_notes[mark_type][i]
                query = 'update cards set data="" where nid=?'
                mw.col.db.execute(query, nid)
                self.redo_search = True

            self.update_mark_items(mark_type)


        remove_ignored_button = QPushButton('Remove Ignored')
        remove_ignored_button.clicked.connect(partial(_remove, 'ignore'))
        self.settings_tab.layout.addWidget(remove_ignored_button, 2, 0)

        remove_known_button = QPushButton('Remove Known')
        remove_known_button.clicked.connect(partial(_remove, 'known'))
        self.settings_tab.layout.addWidget(remove_known_button, 2, 1)

        self.settings_tab.setLayout(self.settings_tab.layout)


    @pyqtSlot()
    def on_active_changed(self):
        self.read_config()
        self.config[self.config_key] = self.combo_box.currentText()

    def create_decks_tab(self):
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
        self.filter_box.setPlaceholderText('汉子')

        self.target_deck = QComboBox(self)
        decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        selected_did = self.editor.parentWindow.deckChooser.selectedId()
        selected_index = -1
        self.decks = {}
        for i, (deck_id, deck_info) in enumerate(decks.items()):
            deck_name = deck_info['name']
            self.target_deck.addItem(deck_name)
            self.decks[deck_name] = deck_id
            if int(deck_id) == selected_did:
                selected_index = i

        if selected_index >= 0:
            self.target_deck.setCurrentIndex(selected_index)

        self.find_tab.layout = QVBoxLayout(self)
        self.find_tab.setLayout(self.find_tab.layout)
        group = QGroupBox()
        group.layout = QGridLayout()
        group.setLayout(group.layout)
        group.layout.addWidget(QLabel('Difficulty'), 0, 0)
        group.layout.addWidget(QLabel('Filter'), 0, 1)
        group.layout.addWidget(QLabel('Target Deck'), 0, 2)
        group.layout.addWidget(self.difficulty_slider, 1, 0)
        group.layout.addWidget(self.filter_box, 1, 1)
        group.layout.addWidget(self.target_deck, 1, 2)
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
        mark_sentences_button = QPushButton('Mark Sentence(s)')
        mark_sentences_button.clicked.connect(self.mark_sentences)
        mark_words_button = QPushButton('Mark Words(s)')
        mark_words_button.clicked.connect(self.mark_words)

        close_button = QPushButton('Close')
        close_button.clicked.connect(self.close)
        button_group.layout.addWidget(add_button, 0, 0)
        button_group.layout.addWidget(add_cloze_button, 0, 1)
        button_group.layout.addWidget(mark_sentences_button, 0, 2)
        button_group.layout.addWidget(mark_words_button, 0, 3)
        button_group.layout.addWidget(close_button, 0, 4)
        button_group.setFixedHeight(75)
        button_group.setFixedWidth(650)
        add_button.setFixedWidth(110)
        add_cloze_button.setFixedWidth(110)
        close_button.setFixedWidth(110)
        self.find_tab.layout.addStretch()
        self.find_tab.layout.addWidget(button_group, 3)

        self.search_button.setFixedWidth(110)
        self.difficulty_slider.setFixedWidth(300)
        self.filter_box.setFixedWidth(300)

    def add(self):
        target_did = self.decks[self.target_deck.currentText()]

        note_ids = [self.search_results[row.row()][0]
                    for row in self.table_widget.selectionModel().selectedRows()]

        note_ids_str = ', '.join([str(n) for n in note_ids])
        cards = mw.col.db.all('select * from cards where nid in (%s)' % note_ids_str)
        for card in cards:
            # Create a new card id
            new_card = (maxID(mw.col.db), card[1], target_did, *card[3:])

            templ_str = ','.join(['?']*len(new_card))
            insert_query = 'insert into cards values (%s)' % templ_str
            mw.col.db.execute(insert_query, *new_card)

        for nid in note_ids:
            mw.col.db.execute('update cards set data="added" where nid=?', nid)

        self.remove_table_rows(row.row() for row in self.table_widget.selectionModel().selectedRows())
        showInfo('Added %i cards from %s notes' % (len(cards), len(note_ids)))

    def mark_sentences(self):
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if len(selected_rows) == 0:
            showInfo("No sentences selected")
            return

        dialog = QDialog()
        dialog.layout = QVBoxLayout(self)

        note = QLabel('Sentences selected: %i' % len(selected_rows))
        dialog.layout.addWidget(note, 0)

        def _mark(mark_type):
            remove = []
            for row in self.table_widget.selectionModel().selectedRows():
                nid, *_ = self.search_results[row.row()]
                query = 'update cards set data=? where nid=?'
                mw.col.db.execute(query, mark_type, nid)
                remove.append(row.row())

            self.update_mark_items(mark_type)

            for row in remove:
                self.table_widget.removeRow(row)
            self.search_results = [s for i, s in enumerate(self.search_results)
                                   if i not in remove]
            dialog.close()

        ignore_button = QPushButton("Mark as Ignored")
        dialog.layout.addWidget(ignore_button, 2)
        ignore_button.clicked.connect(partial(_mark, 'ignore'))

        known_button = QPushButton("Mark as Known")
        dialog.layout.addWidget(known_button, 3)
        known_button.clicked.connect(partial(_mark, 'known'))

        cancel_button = QPushButton("Cancel")
        dialog.layout.addWidget(cancel_button, 4)
        cancel_button.clicked.connect(lambda: dialog.close())
        dialog.setWindowTitle("Mark Sentences")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setLayout(dialog.layout)
        dialog.exec_()

    def remove_table_rows(self, rows):
        for row in rows:
            self.table_widget.removeRow(row)

        self.search_results = [s for i, s in enumerate(self.search_results)
                               if i not in rows]

    def mark_words(self):
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if len(selected_rows) == 0:
            showInfo("No sentences selected")
            return

        remove = []
        for row in self.table_widget.selectionModel().selectedRows():
            nid, field_idx, fields, words, _ = self.search_results[row.row()]
            field = fields[field_idx]

            # Sort by start index
            words = sorted(words, key=lambda w: w[1])
            if not self.select_mark_words_dialog(nid, words, fields, field_idx):
                # not cancelled
                remove.append(row.row())

        self.remove_table_rows(remove)

    def select_mark_words_dialog(self, nid, words, fields, field_idx):
        dialog = QDialog()
        dialog.layout = QVBoxLayout(self)

        note = QLabel('Note:\n' + '\n'.join(fields))
        dialog.layout.addWidget(note, 0)

        model = QStandardItemModel()
        items = []
        word_indices = []
        for i, (info, start, end, strength) in enumerate(words):
            if strength < 0:
                continue
            item = QStandardItem(fields[field_idx][start:end])
            item.setCheckState(Qt.Checked if 0 <= strength < 1 else Qt.Unchecked)
            item.setCheckable(True)
            model.appendRow(item)
            items.append(item)
            word_indices.append(i)

        view = QListView()
        view.setModel(model)
        dialog.layout.addWidget(view, 1)

        def _mark(mark_type):
            selected = []
            for item, i in zip(items, word_indices):
                if item.checkState() != Qt.Checked:
                    continue

                info_words = sorted(words[i][0], key=lambda w: len(w[1]))
                nid, _ = info_words[0] # use the shortest info word
                query = 'update cards set data=? where nid=?'
                mw.col.db.execute(query, mark_type, nid)

            self.update_mark_items(mark_type)
            dialog.close()

        ignore_button = QPushButton("Mark as Ignored")
        dialog.layout.addWidget(ignore_button, 2)
        ignore_button.clicked.connect(partial(_mark, 'ignore'))

        known_button = QPushButton("Mark as Known")
        dialog.layout.addWidget(known_button, 3)
        known_button.clicked.connect(partial(_mark, 'known'))

        cancel_button = QPushButton("Cancel")
        dialog.layout.addWidget(cancel_button, 4)
        cancelled = False
        def _cancel():
            nonlocal cancelled
            cancelled = True
            dialog.close()
        cancel_button.clicked.connect(_cancel)
        dialog.setWindowTitle("Cloze Words")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setLayout(dialog.layout)
        dialog.exec_()
        return cancelled

    def get_translations(self, word, info):
        # info is list of notes (nid, field) that matched a word in a sentence
        valid_field_names = ['English', 'english', 'en', 'En', 'eng']
        for nid, sentence in info:
            if nid == -1:
                yield self.cedict[sentence][-1] # cedict translation
                continue

            if len(sentence) != len(word):
                continue
            mid, flds = mw.col.db.all('select mid, flds from notes where id = %s' % nid)[0]
            flds = flds.split('\x1f')
            model = mw.col.models.get(mid)
            field_names = [field['name'] for field in model['flds']]

            for field_name in valid_field_names:
                if field_name in field_names:
                    yield flds[field_names.index(field_name)]
                    break

    def select_cloze_words_dialog(self, words, fields, field_idx):
        dialog = QDialog()
        dialog.layout = QVBoxLayout(self)

        note = QLabel('Note:\n' + '\n'.join(fields))
        dialog.layout.addWidget(note, 0)

        model = QStandardItemModel()
        items = []
        word_indices = []
        for i, (info, start, end, strength) in enumerate(words):
            if strength < 0:
                continue
            item = QStandardItem(fields[field_idx][start:end])
            item.setCheckState(Qt.Checked if 0 <= strength < 1 else Qt.Unchecked)
            item.setCheckable(True)
            model.appendRow(item)
            items.append(item)
            word_indices.append(i)
        view = QListView()
        view.setModel(model)
        dialog.layout.addWidget(view, 1)

        cancelled = True
        is_joint = False
        def _add(joint):
            nonlocal cancelled
            nonlocal is_joint
            is_joint = joint
            cancelled = False
            dialog.close()

        add_individual_button = QPushButton("Add Separate Clozes")
        dialog.layout.addWidget(add_individual_button, 2)
        add_individual_button.clicked.connect(partial(_add, False))

        add_individual_button = QPushButton("Add Joint Cloze")
        dialog.layout.addWidget(add_individual_button, 3)
        add_individual_button.clicked.connect(partial(_add, True))

        cancel_button = QPushButton("Cancel")
        dialog.layout.addWidget(cancel_button, 4)
        cancel_button.clicked.connect(lambda: dialog.close())
        dialog.setWindowTitle("Cloze Words")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setLayout(dialog.layout)
        dialog.exec_()

        if cancelled:
            return None, False

        selected = []
        for item, i in zip(items, word_indices):
            if item.checkState() == Qt.Checked:
                selected.append(i)
        return selected, is_joint

    def add_cloze(self):
        if len(self.table_widget.selectionModel().selectedRows()) == 0:
            showInfo("No sentences selected")
            return

        target_did = self.decks[self.target_deck.currentText()]
        added = 0
        remove = []
        for row in self.table_widget.selectionModel().selectedRows():
            nid, field_idx, fields, words, _ = self.search_results[row.row()]
            field = fields[field_idx]

            # Sort by start index
            words = sorted(words, key=lambda w: w[1])
            selected_words, joint = self.select_cloze_words_dialog(words, fields, field_idx)
            if selected_words is None:
                continue

            curr_idx = 0
            cloze = ''
            cloze_words = ''
            next_close_idx = 1
            for i, (info, start, end, strength) in enumerate(words):
                if i not in selected_words:
                    cloze += field[start:end]
                elif start > curr_idx:
                    cloze += field[curr_idx:start]
                else:
                    translations = self.get_translations(field[start:end], info)
                    cloze += '{{c%i::%s::%s}}' % (next_close_idx,
                                                  field[start:end],
                                                  list(translations)[0])
                    if not joint:
                        next_close_idx += 1
                curr_idx = end
            if curr_idx < len(field):
                cloze += field[curr_idx:]

            cloze_model = mw.col.models.byName("Cloze")
            cloze_model['did'] = target_did
            mw.col.models.save(cloze_model)
            mw.col.models.setCurrent(cloze_model)
            f = mw.col.newNote(forDeck=False)
            f['Text'] = cloze
            f['Extra'] = '<br/>'.join([f for i, f in enumerate(fields) if i != field_idx])
            mw.col.addNote(f)

            mw.col.db.execute('update cards set data="added" where nid=?', nid)

            added += 1 if joint else next_close_idx - 1
            remove.append(row.row())

        self.remove_table_rows(remove)

        if added > 0:
            showInfo('Added %i card%s' % (added, 's' if added > 1 else ''))

    def difficulty_changed(self):
        self.curr_difficulty = self.difficulty_slider.value()

    def search(self):
        filter_text = self.filter_box.text()

        if self.redo_search:
            self.prepare_search()
            self.redo_search = False

        if filter_text != '':
            sentence_filter = lambda s: filter_text in s[2][s[1]]
        else:
            sentence_filter = lambda s: self.curr_difficulty < s[-1] < self.max_difficulty
        sentences = sorted([s for s in self.sentences if sentence_filter(s)],
                           key=lambda x: x[-1])
        self.search_results = sentences[:self.max_num_results]

        if len(self.search_results) == 0:
            showInfo('No matches')
            self.filter_box.clear()
            return

        self.table_widget.clear()
        for i in range(self.num_columns):
            self.table_widget.setHorizontalHeaderItem(i, QTableWidgetItem('Field %s' % (i+1)));
            self.table_widget.setColumnWidth(i, 300)

        self.table_widget.setRowCount(len(self.search_results))

        for i, (nid, field_idx, fields, words, difficulty) in enumerate(self.search_results):
            colors = []
            sentence = fields[field_idx]
            for _, start, end, strength in words:
                if strength < 0:
                    colors.append('white')
                elif 0 <= strength < 0.2:
                    colors.append('rgb(239, 75, 67)') # red
                elif 0.2 <= strength < 0.4:
                    colors.append('rgb(255, 255, 112)') # yellow
                elif 0.4 <= strength < 0.6:
                    colors.append('rgb(229, 229, 229)') # gray
                elif 0.6 <= strength < 0.8:
                    colors.append('rgb(165, 224, 172)') # light green
                elif 0.8 <= strength <= 1:
                    colors.append('rgb(74, 155, 62)') # green

            label = ''.join('<span style="background: %s; border-color: black">%s</span><span> </span>'
                            % (color, sentence[start:end])
                            for color, (_, start, end, _) in zip(colors, words))

            self.table_widget.setCellWidget(i, 0, QLabel(label))
            for j, k in enumerate([k for k in range(len(fields)) if k != field_idx]):
                self.table_widget.setCellWidget(i, j+1, QLabel(fields[k]))
                if j >= self.num_columns-1:
                    break
            self.table_widget.setCellWidget(i, self.num_columns-1, QLabel(str(difficulty)))
        self.table_widget.resizeRowsToContents()
        self.table_widget.resizeColumnsToContents()
        self.table_widget.show()

    def prepare_search(self):
        self.read_config()
        decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        known_decks = self.config['known_vocabulary_decks']
        active_decks = self.config['active_vocabulary_decks']
        sentence_decks = self.config['sentence_decks']
        user_decks = (list(zip(known_decks, [True]*len(known_decks))) +
                      list(zip(active_decks, [False]*len(active_decks))))
        vocab_strengths = defaultdict(list)
        vocab_info = defaultdict(list)

        def _iter_note_hanzi(deck_name, filter_marked=False):
            did = self.get_did_from_name(deck_name, decks)
            if did is None:
                return
            extra = 'and data=="" ' if filter_marked else ''
            cards = mw.col.db.all("select nid, max(reps-lapses), data from cards where did=%s %sgroup by nid" % (did, extra))

            ids_str = ', '.join(str(nid) for nid, _, _ in cards)
            note_fields = mw.col.db.all("select id, flds from notes where id in (%s)" % ids_str)
            note_fields = {nid: fields.split('\x1f') for nid, fields in note_fields}
            for nid, reps_min_lapses, data in cards:
                fields = note_fields[nid]
                for i, field in enumerate(fields):
                    if len(filter_text_hanzi(field)) == 0:
                        continue
                    yield nid, 10 if data == 'known' else reps_min_lapses, i, fields

        for deck_name, is_known in user_decks:
            for nid, reps_min_lapses, field_idx, fields in _iter_note_hanzi(deck_name):
                splits = split_hanzi(fields[field_idx])

                if len(splits) != 1:
                    # add the sentence as well, so they're filtered out in the
                    # sentence search
                    splits.append(''.join(splits))
                    splits.append(fields[field_idx])

                for word in splits:
                    vocab_strengths[word].append(1.0 if is_known else
                                                 min((reps_min_lapses) / 10, 1.0))
                    vocab_info[word].append((nid, fields[field_idx]))

        for i, (trad, simpl, *_) in enumerate(self.cedict):
            for w in [trad, simpl]:
                vocab_info[w].append((-1, i))
                vocab_strengths[w].append(0.0)


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
            for nid, reps_min_lapses, field_idx, fields in _iter_note_hanzi(deck_name, True):
                field = fields[field_idx]
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
                        words.append(([], non_hanzi_start, curr_idx, -1.0))
                        non_hanzi_start = -1

                    for word in char_to_words[curr_char]:
                        if field[curr_idx:curr_idx+len(word)] != word:
                            continue
                        if (len(word) == len(field) or
                           len(filter_text_hanzi(word)) == len(filter_text_hanzi(field))):
                            continue
                        strength = min(1.0, sum(vocab_strengths[word]))
                        words.append((vocab_info[word], curr_idx, curr_idx+len(word), strength))
                        # -1 because it'll be incremented right after
                        curr_idx += len(word) - 1
                        break
                    curr_idx += 1
                difficulty = sum(10*(1-w[-1]) for w in words if w[-1] >= 0)
                sentences.append((nid, field_idx, fields, words, difficulty))

        self.sentences = sentences

    def get_target_deck(self):
        return self.editor.parentWindow.deckChooser.selectedId()
