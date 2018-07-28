"""
Operations we need:
1. For each sentence, calculate score by going through each word and getting
   anki info (for finding good sentences)
1.5 Find sentences with exactly one missing word, or where all words are known
    but some not so well
2. For each cedict word, find how many sentences contains it and their scores
   (for finding good words)
3. Find sentences which contain an anki note (for showing how many sentences
   there are for a card we're studying

After sentences cards/notes are added, they are marked in the database so that
we can filter them out in future searches

When adding a sentence or word from our own database, we add a field to the
model which refers back to the sentence/word id
"""

import os
import re
import json
import hashlib
import sqlite3
from collections import defaultdict
from aqt import mw

from .han import filter_text_hanzi


def _executemany_select(c, statement, args):
    for a in args:
        c.execute(statement, a)
        yield c.fetchone()


def _get_content_hash_and_str(json_content):
    content = json.dumps(json_content)
    m = hashlib.sha256()
    m.update(content.encode('utf-8'))
    h = m.digest()
    return h[:8], content

def _load_cedict(filename):
    cedict = []
    with open(filename, 'r', encoding="utf-8") as f:
        for line in f:
            if line.startswith('#'):
                continue
            tr, sm, pi, trans = re.match(r"(\S*) (\S*) \[(.*)\] \/(.*)\/", line).groups()
            trans = trans.split('/')
            trans = [t for t in trans if not t.startswith('see also ')]
            cedict.append((tr, sm, pi, trans))

    # Build a map from first character to full words
    cedict_char_to_idx = defaultdict(list)
    for cedict_idx, (tr, sm, *_) in enumerate(cedict):
        cedict_char_to_idx[tr[0]].append((cedict_idx, 0))
        cedict_char_to_idx[sm[0]].append((cedict_idx, 1))

    # Sort the word lists so we always check longest word first
    for key, words in cedict_char_to_idx.items():
        cedict_char_to_idx[key] = sorted(words, key=lambda x: len(cedict[x[0]][0]), reverse=True)

    return cedict, cedict_char_to_idx


class RememberberryDatabase:
    def __init__(self, filename, col=None):
        self.db_filename = filename
        self.decks = None
        self.models = None
        self.col = col if col is not None else mw.col

    def _get_cursor(self):
        return self.col.db._db.cursor()

    def _get_did_from_name(self, deck_name):
        dids = [deck_id for (deck_id, deck_info) in self.decks.items()
               if deck_info['name'] == deck_name]
        if len(dids) == 0:
            return None
        return dids[0]

    def _iter_notes(self, deck_name, filter_linked=False):
        did = self._get_did_from_name(deck_name)
        if did is None:
            return
        filter_str = '''
            AND NOT EXISTS
            (SELECT * FROM rb.note_links WHERE rb.note_links.nid == nid)'''
        c = self._get_cursor()
        res = c.execute('''
           SELECT nid, max(reps-lapses), data FROM cards
           WHERE did=? %sGROUP BY nid
           ''' % (filter_str if filter_linked else '', ), (did,)).fetchall()
        other = {nid: _ for nid, *_ in res}
        ids_str = ', '.join(str(nid) for nid, *_ in res)
        note_fields = c.execute(
                "SELECT id, flds, mid FROM notes WHERE id in (%s)" % ids_str).fetchall()
        for nid, fields, mid in note_fields:
            yield (nid, mid, fields.split('\x1f'), *other[nid])

    def _get_field_from_name(self, mid, fields, valid_names):
        for i, f in enumerate(self.col.models.get(mid)['flds']):
            if f['name'].lower() in valid_names:
                return fields[i]
        return None

    def _find_hanzi_field(self, fields):
        max_len = -1
        max_field = None
        for i, f in enumerate(fields):
            l = len(filter_text_hanzi(f))
            if l > max_len:
                max_len = l
                max_field = f
        return f

    def _iter_notes_cedicts(self, decks, filter_linked=False):
        hanzi_names = set(['hanzi', 'characters', 'simplified'])
        pinyin_names = set(['pinyin'])
        english_names = set(['english', 'translation'])
        for deck in decks:
            for nid, mid, fields, *_ in self._iter_notes(deck, filter_linked):
                hanzi_field = self._get_field_from_name(mid, fields, hanzi_names)
                if hanzi_field == None:
                    # As a fall back, find the field with the most hanzi characters
                    hanzi_field = self._find_hanzi_field(fields)
                pinyin_field = self._get_field_from_name(mid, fields, pinyin_names)
                english_field = self._get_field_from_name(mid, fields, english_names)

                taken = len(hanzi_field)*[0]
                cedicts = []
                for char_idx, char in enumerate(hanzi_field):
                    for cedict_idx, hz_type in self.cedict_char_to_idx[char]:
                        hz = self.cedict[cedict_idx][hz_type]
                        if hanzi_field[char_idx:char_idx+len(hz)] != hz:
                            continue
                        if sum(taken[char_idx:char_idx+len(hz)]) > 0:
                            continue

                        cedicts.append((cedict_idx, char_idx, len(hz)))
                        taken[char_idx:char_idx+len(hz)] = len(hz)*[1]
                yield nid, hanzi_field, pinyin_field, english_field, cedicts

    def update(self, word_decks):
        self.attach()
        c = self._get_cursor()

        # 1. Load user words and cross reference cedict and add note links
        # but only for cards that have not been inserted yet, or not updated
        note_links = []
        for nid, *content, cedicts in self._iter_notes_cedicts(word_decks, True):
            for cedict_idx, start, length in cedicts:
                cedict_hash = self.cedict_hash_json[cedict_idx][0]
                note_links.append((cedict_hash, nid))

        c.executemany('''
            INSERT OR IGNORE INTO rb.note_links VALUES (?, ?)
        ''', note_links)

        c.execute('DROP TABLE IF EXISTS changed_tmp')
        c.execute('DROP TABLE IF EXISTS new_tmp')

        # 2. Update scores
        # 2.1. Find cards where a card's reps or lapses changed
        c.execute('''
            CREATE TEMPORARY TABLE changed_tmp AS
                SELECT id, cards.nid, cards.reps, cards.lapses FROM cards
                JOIN rb.last_updated ON cards.id=rb.last_updated.cid
                WHERE (cards.reps != rb.last_updated.reps OR
                       cards.lapses != rb.last_updated.lapses)
        ''')

        # 2.2. Find cards that are new (not yet present in rb.last_updated)
        c.execute('''
            CREATE TEMPORARY TABLE new_tmp AS
                SELECT id, nid, cards.reps, cards.lapses FROM cards
                WHERE cards.id NOT IN (SELECT cid FROM rb.last_updated)
        ''')

        # 2.3. Update the rb.last_updated table with the changed and new values
        # 2.3.1 Update the rb.last_updated table by first updating changes
        c.execute('''
            UPDATE rb.last_updated
            SET reps=(SELECT reps FROM changed_tmp WHERE rb.last_updated.cid=changed_tmp.id),
                lapses=(SELECT lapses FROM changed_tmp WHERE rb.last_updated.cid=changed_tmp.id)
            WHERE EXISTS (SELECT * FROM changed_tmp WHERE rb.last_updated.cid=changed_tmp.id)
        ''')

        # 2.3.2 Then inserting new
        c.execute('''
            INSERT INTO rb.last_updated (cid, nid, reps, lapses)
            SELECT id, nid, reps, lapses FROM changed_tmp
        ''')

        # 2.4. Find the sum of the reps and lapses in the new and changed groups of cards
        changed = c.execute('''
            SELECT nid, SUM(reps), SUM(lapses) FROM changed_tmp GROUP BY nid
        ''').fetchall()
        new = c.execute('''
            SELECT nid, SUM(reps), SUM(lapses) FROM new_tmp GROUP BY nid
        ''').fetchall()

        # 2.5. Finally update the scores that have changed due to 'changed' and 'new'
        # 2.5.1. Find items that should be updated via note_links
        updated_notes = changed+new

        hashes = list(_executemany_select(c,
            'SELECT hash FROM rb.note_links WHERE nid=?',
            [(nid,) for nid, _, _ in updated_notes]))
        hashes = [h[0] if isinstance(h, tuple) else h for h in hashes]

        # Filter out rows where there was no hash for the nid
        updated_hashes = [h for h in hashes if h is not None]
        updated_notes = [n for n, h in zip(updated_notes, hashes) if h is not None]

        prev_reps_lapses = list(_executemany_select(c,
            'SELECT SUM(reps), SUM(lapses) FROM cards WHERE nid=? GROUP BY nid',
            [(nid,) for nid, _, _ in updated_notes]))

        curr_reps_lapses = [(r, l) for _, r, l in updated_notes]
        diff_reps_lapses = [(r1-r0, l1-l0) for ((r0, l0), (r1, l1))
                            in zip(prev_reps_lapses, curr_reps_lapses)]
        updates = [(r, l, h) for h, (_, r, l) in zip(updated_hashes, updated_notes)]
        c.executemany('UPDATE rb.items SET sum_reps=?, sum_lapses=? WHERE hash=?',
                      updates)

        # 2.5.2. Find linked items (parents) via item_links
        parent_hashes = list(_executemany_select(
            c, 'SELECT from_hash FROM rb.item_links WHERE to_hash=?',
            [(h,) for h in updated_hashes]))


        # 2.5.3. Update the scores of the affected items
        parent_updates = []
        for (dr, dl), hs in zip(diff_reps_lapses, parent_hashes):
            if hs is None: continue
            for h in hs: parent_hashes.append((dr, dl, h))

        c.executemany('''
            UPDATE rb.items
            SET sum_reps=sum_reps+?, sum_lapses=sum_lapses+?
            WHERE hash=?
        ''', parent_updates)

        print('Parent updates: ', parent_updates[:10])

        print('Changed: %i' % len(changed))
        print('New: %i' % len(new))

        # Drop the temporary tables
        c.execute('DROP TABLE changed_tmp')
        c.execute('DROP TABLE new_tmp')
        self.detach()

    def attach(self):
        c = self._get_cursor()
        self.col.db._db.commit()
        try:
            c.execute("ATTACH DATABASE ? AS rb", (self.db_filename,))
        except sqlite3.OperationalError:
            print("Database already attached, it's fine")

    def detach(self):
        c = self._get_cursor()
        self.col.db._db.commit()
        c.execute("DETACH DATABASE rb")

    def init(self, word_decks, sentence_decks):
        self.attach()
        c = self._get_cursor()
        self.decks = json.loads(c.execute("select decks from col").fetchall()[0][0])
        self.models = json.loads(c.execute("select models from col").fetchall()[0][0])

        # 1. Create tables
        tables = ['rb.items', 'rb.item_links', 'rb.note_links',
                  'rb.last_updated', 'rb.hsk']
        for table in tables:
            c.executescript('DROP TABLE IF EXISTS %s;' % table)

        c.execute('''
            CREATE TABLE rb.items (
                hash CHARACTER(8) PRIMARY KEY,
                prev_hash CHARACTER(8),
                content VARCHAR,
                type VARCHAR,
                sum_reps INTEGER,
                sum_lapses INTEGER,
                sum_links INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE rb.item_links (
                from_hash CHARACTER(8),
                to_hash CHARACTER(8),
                pointer VARCHAR,
                PRIMARY KEY (from_hash, to_hash),
                FOREIGN KEY(from_hash) REFERENCES items(hash),
                FOREIGN KEY(to_hash) REFERENCES items(hash)
            )
        ''')
        c.execute('''
            CREATE TABLE rb.note_links (
                hash CHARACTER(8),
                nid INTEGER,
                PRIMARY KEY (hash, nid),
                FOREIGN KEY(hash) REFERENCES items(hash)
            )
        ''')
        c.execute('''
            CREATE TABLE rb.last_updated (
                cid INTEGER,
                nid INTEGER,
                reps INTEGER,
                lapses INTEGER,
                PRIMARY KEY (cid)
            )
        ''')

        c.execute('''
            CREATE TABLE rb.hsk (
                hash CHARACTER(8),
                level INTEGER,
                PRIMARY KEY(hash),
                FOREIGN KEY(hash) REFERENCES items(hash)
            )
        ''')

        # 2. Load cedict into items
        # 2.1. Load the cedict file
        sources_dir = os.path.join(os.path.dirname(__file__), 'corpus/sources')
        cedict_file = os.path.join(sources_dir, 'cedict_ts.u8')
        self.cedict, self.cedict_char_to_idx = _load_cedict(cedict_file)

        # 2.2. Load HSK files
        hsk = {}
        for lvl in range(1, 7):
            cedict_file = os.path.join(sources_dir, 'HSK%i.txt' % lvl)
            lvl_words = set(open(cedict_file, 'r', encoding='utf-8').readlines())
            hsk[lvl] = lvl_words

        # 2.3. Create json content for each and hash it
        self.cedict_hash_json = []
        self.cedict_hsk = []
        for c_data in self.cedict:
            h_64, content = _get_content_hash_and_str(c_data)
            self.cedict_hash_json.append((h_64, content))
            word_level = 0
            for lvl in range(1, 7):
                if c_data[1] in hsk[lvl]:
                    word_level = lvl
                    break
            self.cedict_hsk.append((h_64, word_level))


        # 2.4. Insert into items table with hash as id
        c.executemany('''INSERT OR REPLACE INTO rb.items VALUES (
                         ?, NULL, ?, "cedict", NULL, NULL, NULL)''', self.cedict_hash_json)

        # 2.5. Insert into hsk table
        c.executemany('''INSERT OR REPLACE INTO rb.hsk VALUES (?, ?)''', self.cedict_hsk)

        # 3. Load sentences into items and cross reference cedict and add item links
        links = []
        sentences = []
        for nid, *content, cedicts in self._iter_notes_cedicts(sentence_decks):
            h_64, content = _get_content_hash_and_str([None, *content])
            sentences.append((h_64, content, 'user_sentence'))
            for cedict_idx, start, length in cedicts:
                link_pointer = '%i-%i' % (start, start+length)
                cedict_hash = self.cedict_hash_json[cedict_idx][0]
                links.append((h_64, cedict_hash, link_pointer))

        c.executemany('''INSERT OR REPLACE INTO rb.items VALUES (
                           ?, NULL, ?, ?, NULL, NULL, NULL
                         )''', sentences)
        c.executemany('''INSERT OR REPLACE INTO rb.item_links VALUES (?, ?, ?)''', links)

        # 4. Populate/update user words and the scores table
        self.update(word_decks)


def load_sentence_index(sentence_decks):
    global cedict_to_sentence_nids, sentence_nid_to_cedicts
    cedict_to_sentence_nids, sentence_nid_to_cedicts = _get_cedict_note_maps(sentence_decks)


def load_word_index(word_decks):
    global cedict_to_nids, nid_to_cedicts
    cedict_to_nids, nid_to_cedicts = _get_cedict_note_maps(word_decks)


def load_word_strengths(word_decks):
    global nid_to_strength
    for deck in word_decks:
        for nid, *_, reps_min_lapses, data in self._iter_notes(deck):
            reps_min_lapses = 10 if data == 'known' else reps_min_lapses
            strength = min((reps_min_lapses) / 10, 1.0)
            nid_to_strength[nid] = strength


def get_sentence_difficulties():
    for sentence_nid, (cedicts, fields) in sentence_nid_to_cedicts.items():
        strengths = []
        cedict_fields = len(fields)*[0]
        for cedict_idx, _, field_idx, _ in cedicts:
            max_strength = 0
            words, _ = cedict_to_nids.get(cedict_idx, ([], []))
            for nid, *_ in words:
                strength = nid_to_strength[nid]
                max_strength = max(max_strength, strength)
            strengths.append(max_strength)
            cedict_fields[field_idx] += 1
        difficulty = sum(10*(1-s) for s in strengths)
        # Find the most common field idx
        field_idx = cedict_fields.index(max(cedict_fields))
        yield sentence_nid, field_idx, fields, difficulty

