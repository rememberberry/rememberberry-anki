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
import base64
from functools import wraps

from collections import defaultdict
from aqt import mw


def _get_content_hash_and_str(json_content):
    content = json.dumps(json_content)
    m = hashlib.sha256()
    m.update(content.encode('utf-8'))
    h = base64.b64encode(m.digest())
    return str(h[:16], 'utf-8'), content

def _load_cedict(filename, hsk=None):
    cedict = []
    with open(filename, 'r', encoding="utf-8") as f:
        for line in f:
            if line.startswith('#'):
                continue
            tr, sm, py, transl = re.match(r"(\S*) (\S*) \[(.*)\] \/(.*)\/", line).groups()
            transl = transl.split('/')
            transl = [t for t in transl if not t.startswith('see also ')]
            cedict.append((tr, sm, py, transl))

    # Build a map from first character to full words
    cedict_char_to_idx = defaultdict(list)
    for cedict_idx, (tr, sm, *_) in enumerate(cedict):
        cedict_char_to_idx[tr[0]].append((cedict_idx, 0))
        cedict_char_to_idx[sm[0]].append((cedict_idx, 1))

    # Sort the word lists first by length, then by hsk level
    # so we always check longest word first, and with a preference for lowest hsk level
    def sort_key(x):
        hz = cedict[x[0]][1]
        word_level = 9 # unknown
        for lvl in range(1, 7):
            if hsk is None: break
            if hz in hsk[lvl]:
                word_level = lvl
                break
        return '%02d-%02d' % (len(hz), 9-word_level)

    for key, words in cedict_char_to_idx.items():
        cedict_char_to_idx[key] = sorted(words, key=sort_key, reverse=True)

    return cedict, cedict_char_to_idx


def attach_detach(method):
    @wraps(method)
    def _impl(self, *args, **kwargs):
        self.attach()
        try:
            return method(self, *args, **kwargs)
        finally:
            self.detach()

    return _impl


class RememberberryDatabase:
    def __init__(self, filename, col=None, completed_hsk_lvl=0):
        self.db_filename = filename
        self.decks = None
        self.models = None
        self.col = col if col is not None else mw.col
        self.completed_hsk_lvl = completed_hsk_lvl

    @property
    def exists(self):
        return os.path.exists(self.db_filename)

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
        try:
            c.execute("DETACH DATABASE rb")
        except sqlite3.OperationalError:
            print("Database already detached, it's fine")

    @attach_detach
    def init(self, word_decks, sentence_decks):
        self.attach()
        c = self._get_cursor()
        self.decks = json.loads(c.execute("select decks from col").fetchall()[0][0])
        self.models = json.loads(c.execute("select models from col").fetchall()[0][0])

        # 1. Create tables
        tables = ['rb.items', 'rb.item_links', 'rb.item_search', 'rb.note_links',
                  'rb.last_updated', 'rb.hsk']
        for table in tables:
            c.executescript('DROP TABLE IF EXISTS %s;' % table)

        c.execute('''
            CREATE TABLE rb.items (
                hash CHARACTER(16) PRIMARY KEY,
                prev_hash CHARACTER(16),
                content VARCHAR,
                type VARCHAR,

                max_correct INTEGER,
                num_known INTEGER,
                num_memorizing INTEGER,
                num_learning INTEGER,
                num_unknown INTEGER,
                num_links INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE rb.item_links (
                from_hash CHARACTER(16),
                to_hash CHARACTER(16),
                pointer VARCHAR,
                PRIMARY KEY (from_hash, to_hash),
                FOREIGN KEY(from_hash) REFERENCES items(hash),
                FOREIGN KEY(to_hash) REFERENCES items(hash)
            )
        ''')
        c.execute('''
            CREATE INDEX rb.links_from_hashes ON item_links (from_hash);
        ''')
        c.execute('''
            CREATE INDEX rb.links_to_hashes ON item_links (to_hash);
        ''')
        c.execute('''
            CREATE INDEX rb.search_hashes ON items (hash);
        ''')
        c.execute('''
            CREATE TABLE rb.note_links (
                hash CHARACTER(16),
                nid INTEGER,
                PRIMARY KEY (hash, nid),
                FOREIGN KEY(hash) REFERENCES items(hash)
            )
        ''')
        c.execute('''
            CREATE INDEX rb.note_links_nids ON note_links (nid);
        ''')
        c.execute('''
            CREATE INDEX rb.note_link_hashes ON note_links (hash);
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
                hash CHARACTER(16),
                level INTEGER,
                PRIMARY KEY(hash),
                FOREIGN KEY(hash) REFERENCES items(hash)
            )
        ''')

        # 2. Load cedict into items
        # 2.1. Load HSK files
        sources_dir = os.path.join(os.path.dirname(__file__), 'corpus/sources')
        hsk = {}
        for lvl in range(1, 7):
            hsk_file = os.path.join(sources_dir, 'HSK%i.txt' % lvl)
            lvl_words = set(open(hsk_file, 'r', encoding='utf-8').read().splitlines())
            hsk[lvl] = lvl_words

        # 2.2. Load the cedict file
        cedict_file = os.path.join(sources_dir, 'cedict_ts.u8')
        self.cedict, self.cedict_char_to_idx = _load_cedict(cedict_file, hsk)

        # 2.3. Create json content for each and hash it
        self.cedict_hash_json = []
        self.cedict_hsk = []
        for c_data in self.cedict:
            h_64, content = _get_content_hash_and_str(c_data)
            word_level = 9 # unknown
            for lvl in range(1, 7):
                if c_data[1] in hsk[lvl]:
                    word_level = lvl
                    break
            self.cedict_hash_json.append((h_64, content))
            self.cedict_hsk.append((h_64, word_level))

        # 2.4. Insert into items table with hash as id
        c.executemany('''INSERT OR REPLACE INTO rb.items VALUES (
                         ?, NULL, ?, "cedict", 0, 0, 0, 0, 0, 0)''', self.cedict_hash_json)

        # 2.5. Insert into hsk table
        c.executemany('''INSERT OR REPLACE INTO rb.hsk VALUES (?, ?)''', self.cedict_hsk)

        # 3. Load sentences into items and cross reference cedict and add item links
        links = []
        sentences = []
        for nid, *content, cedicts in self._iter_notes_cedicts(sentence_decks, hsk):
            h_64, content = _get_content_hash_and_str([None, *content])
            sentences.append((h_64, content, 'user_sentence'))
            for cedict_idx, start, length in cedicts:
                link_pointer = '%i-%i' % (start, start+length)
                cedict_hash = self.cedict_hash_json[cedict_idx][0]
                links.append((h_64, cedict_hash, link_pointer))

        c.executemany('''INSERT OR REPLACE INTO rb.items VALUES (
                           ?, NULL, ?, ?, 0, 0, 0, 0, 0, 0
                         )''', sentences)
        c.executemany('''INSERT OR REPLACE INTO rb.item_links VALUES (?, ?, ?)''', links)

        # 4. Populate/update user words and the scores table
        self.update(word_decks)

    @attach_detach
    def update(self, word_decks):
        c = self._get_cursor()

        # 1. Load user words and cross reference cedict and add note links
        # but only for cards that have not been inserted yet, or not updated
        note_links = []
        for nid, *content, cedicts in self._iter_notes_cedicts(word_decks, True):
            if len(cedicts) != 1: continue
            cedict_idx, start, length = cedicts[0]
            cedict_hash = self.cedict_hash_json[cedict_idx][0]
            note_links.append((cedict_hash, nid))
        #print('Num note links: %i' % len(note_links))

        c.executemany('''
            INSERT OR IGNORE INTO rb.note_links VALUES (?, ?)
        ''', note_links)

        # 2. Update sum_reps and sum_lapses in rb.items
        # 2.1. Find cards where a card's reps or lapses changed
        changed = [r[0] for r in c.execute('''
            SELECT DISTINCT(cards.nid) FROM cards
            JOIN rb.last_updated ON cards.id=rb.last_updated.cid
            WHERE (cards.reps != rb.last_updated.reps OR
                   cards.lapses != rb.last_updated.lapses)
        ''').fetchall()]

        # 2.2. Find cards that are new (not yet present in rb.last_updated)
        new = [r[0] for r in c.execute('''
            SELECT DISTINCT(nid) FROM cards
            WHERE cards.id NOT IN (SELECT cid FROM rb.last_updated)
        ''').fetchall()]

        # 2.3. Finally update the scores that have changed
        # 2.3.1. Find item hashes that should be updated via note_links
        updated_notes = changed+new

        updated_item_hashes = c.execute(
            'SELECT DISTINCT(hash) FROM rb.note_links WHERE nid IN (%s)' % ','.join(str(n) for n in updated_notes)
        ).fetchall()
        updated_item_hashes = [h[0] for h in updated_item_hashes]
        
        # 2.3.2. Update the items with changed notes
        c.executemany('''
            UPDATE rb.items SET max_correct=(
                SELECT MAX(reps-lapses)
                FROM rb.note_links JOIN cards ON rb.note_links.nid = cards.nid
                WHERE rb.note_links.hash = ?
            )
            WHERE hash = ?
        ''', [2*(h,) for h in updated_item_hashes])

        # 2.3.3. Find linked items (parents) via item_links and update those
        # parents
        parent_hashes = c.execute(
            'SELECT DISTINCT(from_hash) FROM rb.item_links WHERE to_hash IN (%s)' %
            ','.join('"%s"' % s for s in updated_item_hashes)).fetchall()
        parent_hashes = [h[0] for h in parent_hashes]

        l = self.completed_hsk_lvl
        properties = [('num_known', 'AND (max_correct > 8 OR level <= %i)' % l),
                      ('num_memorizing', 'AND (max_correct BETWEEN 5 AND 8 AND level > %i)' % l),
                      ('num_learning', 'AND (max_correct BETWEEN 1 AND 4 AND level > %i)' % l),
                      ('num_unknown', 'AND (max_correct = 0 AND level > %i)' % l),
                      ('num_links', '')]
        for prop in properties:
            c.executemany('''
                UPDATE rb.items SET
                    %s=(
                        SELECT COUNT(*) FROM rb.item_links
                        JOIN rb.items ON rb.items.hash=rb.item_links.to_hash
                        JOIN rb.hsk ON rb.items.hash=rb.hsk.hash
                        WHERE from_hash=? %s
                    )
                WHERE hash = ?
            ''' % prop, [2*(h,) for h in parent_hashes])

        # 2.4. Update the rb.last_updated table with the changed and new values
        # 2.4.1 Update the rb.last_updated table by first updating changes
        c.execute('''
            UPDATE rb.last_updated
            SET reps=(SELECT reps FROM cards WHERE rb.last_updated.cid=cards.id),
                lapses=(SELECT lapses FROM cards WHERE rb.last_updated.cid=cards.id)
            WHERE rb.last_updated.nid IN (%s)
        ''' % ', '.join(str(c) for c in changed))

        # 2.4.2 Then inserting new
        c.execute('''
            INSERT INTO rb.last_updated (cid, nid, reps, lapses)
            SELECT id, nid, reps, lapses FROM cards
            WHERE nid IN (%s)
        ''' % ', '.join(str(n) for n in new))

        return len(new), len(changed), len(parent_hashes)

    @attach_detach
    def search(self, filter_text=None, limit=-1, num_unknown=-1):
        c = self._get_cursor()

        filter_clause = ''
        if filter_text is not None:
            filter_clause = 'AND content like "%%s%"' % filter_text

        unknown_clause = ''
        if num_unknown >= 0:
            unknown_clause = 'AND num_unknown=%i' % num_unknown

        limit_clause = ''
        if limit >= 0:
            limit_clause = 'LIMIT %i' % limit

        items = c.execute('''
            SELECT * FROM rb.items
            WHERE rb.items.type = 'user_sentence' AND NOT EXISTS
            (SELECT * FROM rb.note_links WHERE rb.note_links.hash=rb.items.hash)
            %s %s %s
        ''' % (unknown_clause, filter_clause, limit_clause)).fetchall()

        item_words = []
        for h, *_ in items:
            words = c.execute('''
                SELECT * FROM rb.item_links
                JOIN rb.items ON rb.item_links.to_hash = rb.items.hash
                JOIN rb.hsk ON rb.hsk.hash=rb.items.hash
                WHERE rb.item_links.from_hash=?
            ''', (h,)).fetchall()
            item_words.append(words)
            
        return items, item_words
