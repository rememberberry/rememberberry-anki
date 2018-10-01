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
from time import time
import pickle
from functools import wraps

from collections import defaultdict
from aqt import mw
from aqt.utils import showInfo

from .han import filter_text_hanzi
import jieba


def _get_content_hash(json_content):
    content = json.dumps(json_content)
    m = hashlib.sha256()
    m.update(content.encode('utf-8'))
    h = base64.b64encode(m.digest())
    return str(h[:16], 'utf-8')


def _load_cedict(filename, hsk=None):
    cedict = defaultdict(list)
    with open(filename, 'r', encoding="utf-8") as f:
        for line in f:
            if line.startswith('#'):
                continue
            tr, sm, py, transl = re.match(r"(\S*) (\S*) \[(.*)\] \/(.*)\/", line).groups()
            transl = transl.split('/')
            transl = [t for t in transl if not t.startswith('see also ')]
            cedict[sm].append((tr, py, transl))

    # Find compounds with jieba
    num = 0
    compound_parts = {}
    for sm, entries in cedict.items():
        # search mode will produce compounds and their parts
        tokens = list(jieba.tokenize(sm, mode='search'))
        parts = [t for t in tokens if t[2]-t[1] < len(sm)]
        compound_parts[sm] = parts

    # Join multiple sound characters (多音字)
    cedict = {sm: (sm, entries, compound_parts[sm]) for sm, entries in cedict.items()}
    return cedict

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
        self.col = col if col is not None else mw.col
        self.completed_hsk_lvl = completed_hsk_lvl

        c = self._get_cursor()
        self.decks = json.loads(c.execute("select decks from col").fetchall()[0][0])
        self.models = json.loads(c.execute("select models from col").fetchall()[0][0])

        self._load_hsk_cedict()

    @property
    def exists(self):
        return os.path.exists(self.db_filename)

    def _load_hsk_cedict(self):
        # Load HSK files and cedict
        sources_dir = os.path.join(os.path.dirname(__file__), 'corpus/sources')
        self.hsk = {}
        for lvl in range(1, 7):
            hsk_file = os.path.join(sources_dir, 'HSK%i.txt' % lvl)
            lvl_words = set(open(hsk_file, 'r', encoding='utf-8').read().splitlines())
            # Split up words and add individual characters
            chars = set()
            for word in lvl_words:
                chars = chars | set(word)
            self.hsk[lvl] = lvl_words | chars

        # Load the cedict file
        cedict_file = os.path.join(sources_dir, 'cedict_ts.u8')
        user_files = os.path.join(os.path.dirname(__file__), 'user_files')
        cedict_cache_file = os.path.join(user_files, 'cedict_cache.pickle')
        if os.path.exists(cedict_cache_file):
            with open(cedict_cache_file, 'rb') as f:
                self.cedict = pickle.load(f)
        else:
            self.cedict = _load_cedict(cedict_file, self.hsk)
            with open(cedict_cache_file, 'wb') as f:
                pickle.dump(self.cedict, f)


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

                tokens = list(jieba.tokenize(hanzi_field))
                cedicts = [t for t in tokens if t[0] in self.cedict]
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

        # 1. Create tables
        tables = ['rb.items', 'rb.item_links', 'rb.item_search', 'rb.note_links',
                  'rb.last_updated', 'rb.hsk']
        for table in tables:
            c.executescript('DROP TABLE IF EXISTS %s;' % table)

        c.execute('''
            CREATE TABLE rb.items (
                hash CHARACTER(16) PRIMARY KEY,
                prev_hash CHARACTER(16),
                type VARCHAR,
                data_traditional VARCHAR,
                data_simplified VARCHAR,
                data_pinyin VARCHAR,
                data_translation VARCHAR,

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
                hsk_lvl INTEGER,
                PRIMARY KEY(hash),
                FOREIGN KEY(hash) REFERENCES items(hash)
            )
        ''')


        # 2. Load cedict into items
        # 2.1. Create json content for each and hash it
        self.cedict_hash_json = {}
        self.cedict_hsk = []
        for hz, (_, entries, _) in self.cedict.items():
            traditional = json.dumps([tr for tr, _, _ in entries])
            pinyin = json.dumps([py for _, py, _ in entries])
            translation = json.dumps([transl for _, _, transl in entries])
            h_64 = _get_content_hash((hz, entries))
            word_level = 9 # unknown
            for lvl in range(1, 7):
                if hz in self.hsk[lvl]:
                    word_level = lvl
                    break
            self.cedict_hash_json[hz] = (h_64, traditional, hz, pinyin, translation)
            self.cedict_hsk.append((h_64, word_level))

        # 2.2. Insert into items table with hash as id
        c.executemany('''INSERT OR REPLACE INTO rb.items VALUES (
                         ?, NULL, "cedict", ?, ?, ?, ?, 0, 0, 0, 0, 0, 0)''',
                      list(self.cedict_hash_json.values()))

        # 2.3. Insert into hsk table
        c.executemany('''INSERT OR REPLACE INTO rb.hsk VALUES (?, ?)''', self.cedict_hsk)

        # 3. Add links

        # 3.1. Add links between compound cedict words and their parts
        links = []
        for sm, (*_, compound_parts) in self.cedict.items():
            compound_hash = self.cedict_hash_json[sm][0]
            for part_sm, start, end in compound_parts:
                if part_sm not in self.cedict_hash_json:
                    continue
                part_hash = self.cedict_hash_json[part_sm][0]
                link_pointer = '%i-%i' % (start, end)
                links.append((compound_hash, part_hash, link_pointer))

        # 3.2. Load sentences into items and cross reference cedict and add item links
        sentences = []
        for nid, *content, cedicts in self._iter_notes_cedicts(sentence_decks):
            h_64 = _get_content_hash([None, *content])
            sentences.append((h_64, *content))
            for hz, start, end in cedicts:
                link_pointer = '%i-%i' % (start, end)
                cedict_hash = self.cedict_hash_json[hz][0]
                links.append((h_64, cedict_hash, link_pointer))

        c.executemany('''INSERT OR REPLACE INTO rb.items VALUES (
                           ?, NULL, 'user_sentence', NULL, ?, ?, ?, 0, 0, 0, 0, 0, 0
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
            ## Only link single words
            for hz, start, length in cedicts:
                cedict_hash = self.cedict_hash_json[hz][0]
                note_links.append((cedict_hash, nid))

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
            'SELECT DISTINCT(hash) FROM rb.note_links WHERE nid IN (%s)'
            % ','.join(str(n) for n in updated_notes)
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
        properties = [('num_known', 'AND (max_correct > 8 OR hsk_lvl <= %i)' % l),
                      ('num_memorizing', 'AND (max_correct BETWEEN 5 AND 8 AND hsk_lvl > %i)' % l),
                      ('num_learning', 'AND (max_correct BETWEEN 1 AND 4 AND hsk_lvl > %i)' % l),
                      ('num_unknown', 'AND (max_correct = 0 AND hsk_lvl > %i)' % l),
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
            filter_clause = 'AND data_simplified LIKE "%{}%"'.format(filter_text)

        unknown_clause = ''
        if num_unknown >= 0:
            unknown_clause = 'AND num_unknown=%i' % num_unknown

        limit_clause = ''
        if limit >= 0:
            limit_clause = 'LIMIT %i' % limit

        items = c.execute('''
            SELECT hash, data_simplified, data_pinyin, data_translation FROM rb.items
            WHERE rb.items.type = 'user_sentence' AND NOT EXISTS
            (SELECT * FROM rb.note_links WHERE rb.note_links.hash=rb.items.hash)
            %s %s %s
        ''' % (unknown_clause, filter_clause, limit_clause)).fetchall()

        item_words = []
        for h, *_ in items:
            words = c.execute('''
                SELECT rb.items.hash, pointer, max_correct, hsk_lvl
                FROM rb.item_links
                JOIN rb.items ON rb.item_links.to_hash = rb.items.hash
                JOIN rb.hsk ON rb.hsk.hash=rb.items.hash
                WHERE rb.item_links.from_hash=?
            ''', (h,)).fetchall()

            # Conver the pointer to int tuple
            words = [(h, [int(p) for p in ptr.split('-')], *r)
                     for (h, ptr, *r) in words]
            item_words.append(words)
            
        return list(zip(items, item_words))
