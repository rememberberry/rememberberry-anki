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
import pickle
import sqlite3
from collections import defaultdict
from aqt import mw

def _get_content_hash_and_str(json_content):
    content = json.dumps(c)
    m = hashlib.sha256()
    m.update(content)
    h = m.digest()
    h_64 = int.from_bytes(h[:8], 'big')
    return h_64, content

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
    def __init__(self, filename):
        mw.col.db.execute("ATTACH DATABASE ? AS rb", filename)
        self.all_decks = None
        self.all_models = None

    def _get_did_from_name(self, deck_name):
        dids = [deck_id for (deck_id, deck_info) in self.all_decks.items()
               if deck_info['name'] == deck_name]
        if len(dids) == 0:
            return None
        return dids[0]

    def _iter_notes(self, deck_name, filter_marked=False):
        did = self._get_did_from_name(deck_name)
        if did is None:
            return
        extra = 'and data=="" ' if filter_marked else ''
        res = mw.col.db.all("select nid, max(reps-lapses), data from cards where did=%s %sgroup by nid" % (did, extra))
        other = {nid: _ for nid, *_ in res}
        ids_str = ', '.join(str(nid) for nid, *_ in res)
        note_fields = mw.col.db.all("select id, flds, mid from notes where id in (%s)" % ids_str)
        for nid, fields, mid in note_fields:
            yield (nid, mid, fields.split('\x1f'), *other[nid])

    def _get_field_from_name(self, mid, fields, valid_names):
        for i, f in self.all_models[mid]['flds']:
            if f['name'].tolower() in valid_names:
                return fields[i]
        return None

    def _iter_notes_cedicts(self, decks):
        hanzi_names = set(['hanzi', 'characters', 'simplified', 'Simplified'])
        pinyin_names = set(['pinyin'])
        english_names = set(['english', 'translation'])
        for deck in decks:
            for nid, mid, fields, *_ in self._iter_notes(deck):
                hanzi_field = self._get_field_from_name(mid, fields, hanzi_names)
                pinyin_field = self._get_field_from_name(mid, fields, pinyin_names)
                english_field = self._get_field_from_name(mid, fields, english_names)

                taken = len(hanzi_field)*[0]
                cedicts = []
                for char_idx, char in enumerate(hanzi_field):
                    for cedict_idx, hz_type in cedict_char_to_idx[char]:
                        hz = cedict[cedict_idx][hz_type]
                        if hanzi_field[char_idx:char_idx+len(hz)] != hz:
                            continue
                        if sum(taken[char_idx:char_idx+len(hz)]) > 0:
                            continue

                        cedicts.append((cedict_idx, char_idx, len(hz)))
                        taken[char_idx:char_idx+len(hz)] = len(hz)*[1]
                yield nid, hanzi_field, pinyin_field, english_field, cedicts

    def update(self, word_decks):
        # 
        pass

    def create(self, word_decks, sentence_decks):
        self.all_decks = json.loads(mw.col.db.all("select decks from col")[0][0])
        self.all_models = json.loads(mw.col.db.all("select models from col")[0][0])

        # 1. Create tables
        c = mw.col.db
        c.execute('DROP TABLE rb.items, rb.item_links, rb.note_links')
        c.execute('''
            CREATE TABLE rb.items (
                hash INTEGER PRIMARY KEY,
                prev_hash INTEGER,
                content VARCHAR,
                type VARCHAR
            )
        ''')
        c.execute('''
            CREATE TABLE rb.item_links (
                FOREIGN KEY(from_hash) REFERENCES items(hash),
                FOREIGN KEY(to_hash) REFERENCES items(hash),
                pointer VARCHAR
                PRIMARY KEY (from_hash, to_hash)
            )
        ''')
        c.execute('''
            CREATE TABLE rb.note_links (
                FOREIGN KEY(hash) REFERENCES items(hash),
                note_id INTEGER
                PRIMARY KEY (hash, note_id)
            )
        ''')
        c.execute('''
            CREATE TABLE rb.scores (
                FOREIGN KEY(hash) REFERENCES items(hash),
                sum_score INTEGER,
                max_score INTEGER
                PRIMARY KEY hash
            )
        ''')
        c.execute('''
            CREATE TABLE rb.hsk (
                FOREIGN KEY(hash) REFERENCES items(hash),
                level INTEGER
                PRIMARY KEY hash
            )
        ''')

        # 2. Load cedict into items
        # 2.1. Load the cedict file
        sources_dir = os.path.join(os.path.dirname(__file__), 'corpus')
        cedict_file = os.path.join(sources_dir, 'cedict_ts.u8')
        cedict, cedict_char_to_idx = _load_cedict(cedict_file)

        # 2.2. Load HSK files
        hsk = {}
        for lvl in range(1, 7):
            cedict_file = os.path.join(sources_dir, 'HSK%i.txt' % lvl)
            lvl_words = set(open(cedict_file, 'r').readlines())
            hsk[lvl] = lvl_words

        # 2.3. Create json content for each and hash it
        cedict_hash_json = []
        cedict_hsk = []
        for c in cedict:
            h_64, content = _get_content_hash_and_str(c)
            cedict_hash_json.append((h_64, content))
            word_level = 0
            for lvl in range(1, 7):
                if c[1] in hsk[lvl]:
                    word_level = lvl
                    break
            cedict_hsk.append((h_64, word_level))


        # 2.4. Insert into items table with hash as id
        c.executemany('''INSERT INTO rb.items VALUES (?, NULL, ?, "cedict")''',
                      cedict_hash_json)

        # 2.5. Insert into hsk table
        c.executemany('''INSERT INTO rb.hsk VALUES (?, ?)''', cedict_hsk)

        # 3. Load sentences into items and cross reference cedict and add item links
        #    Load user words and cross reference cedict and add note links
        links = []
        sentences = []
        sentence_items = list(self._iter_notes_cedicts(sentence_decks))
        word_items = list(self._iter_notes_cedicts(word_decks))
        items = (zip(sentence_items, len(sentence_items)*['user_sentence']) +
                 zip(word_items, len(word_items)*['user_word']))
        for (nid, hanzi, pinyin, english, cedicts), _type in items:
            h_64, content = _get_content_hash_and_str([None, hanzi, pinyin, english])
            sentences.append((h_64, content, _type))
            for cedict_idx, start, length in cedicts:
                link_pointer = '%i-%i' % (start, start+length)
                links.append((h_64, cedict_hash_json[cedict_idx][0], link_pointer))

        c.executemany('''INSERT INTO rb.items VALUES (?, NULL, ?, ?)''', sentences)
        c.executemany('''INSERT INTO rb.item_links VALUES (?, ?, ?)''', links)

        # 4. Populate/update the scores table
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
