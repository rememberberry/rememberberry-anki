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
from collections import defaultdict
from aqt import mw


all_decks = None
cedict = None
cedict_char_to_idx = None

cedict_to_nids, nid_to_cedicts = {}, {}
cedict_to_sentence_nids, sentence_nid_to_cedicts = {}, {}

def _get_did_from_name(deck_name):
    dids = [deck_id for (deck_id, deck_info) in all_decks.items()
           if deck_info['name'] == deck_name]
    if len(dids) == 0:
        return None
    return dids[0]


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


def _iter_notes(deck_name, filter_marked=False):
    did = _get_did_from_name(deck_name)
    if did is None:
        return
    extra = 'and data=="" ' if filter_marked else ''
    nids = mw.col.db.all("select nid from cards where did=%s %sgroup by nid" % (did, extra))
    ids_str = ', '.join(str(nid[0]) for nid in nids)
    note_fields = mw.col.db.all("select id, flds from notes where id in (%s)" % ids_str)
    for nid, fields in note_fields:
        yield nid, fields.split('\x1f')


def _get_cedict_note_maps(decks):
    nid_to_cedicts = defaultdict(list)
    cedict_to_nids = defaultdict(list)
    for deck in decks:
        for nid, fields in _iter_notes(deck):
            for field_idx, field in enumerate(fields):
                taken = len(field)*[0]
                for char_idx, char in enumerate(field):
                    for cedict_idx, hz_type in cedict_char_to_idx[char]:
                        hz = cedict[cedict_idx][hz_type]
                        if field[char_idx:char_idx+len(hz)] != hz:
                            continue
                        if sum(taken[char_idx:char_idx+len(hz)]) > 0:
                            continue

                        nid_to_cedicts[nid].append((cedict_idx, hz_type, field_idx, char_idx))
                        cedict_to_nids[cedict_idx].append((nid, hz_type, field_idx, char_idx))
                        taken[char_idx:char_idx+len(hz)] = len(hz)*[1]

    return cedict_to_nids, nid_to_cedicts


def load_cedict_index():
    global all_decks, cedict, cedict_char_to_idx
    all_decks = json.loads(mw.col.db.all("select decks from col")[0][0])
    cedict_file = os.path.join(os.path.dirname(__file__), 'corpus/sources/cedict_ts.u8')
    cedict, cedict_char_to_idx = _load_cedict(cedict_file)


def load_sentence_index(sentence_decks):
    global cedict_to_sentence_nids, sentence_nid_to_cedicts
    cedict_to_sentence_nids, sentence_nid_to_cedicts = _get_cedict_note_maps(sentence_decks)


def load_word_index(user_decks):
    global cedict_to_nids, nid_to_cedicts
    cedict_to_nids, nid_to_cedicts = _get_cedict_note_maps(user_decks)


def create_indexes(user_decks, sentence_decks):
    load_cedict_index()
    load_sentence_index(sentence_decks)
    load_word_index(user_decks)


def _get_indexes_filename(create_dir=False):
    tmp_dir = os.path.join(os.path.dirname(__file__), 'tmp')
    if create_dir:
        try:
            os.makedirs(tmp_dir)
        except:
            pass
    return os.path.join(tmp_dir, 'indexes.pickle')


def save_indexes_to_file(filename=None):
    indexes_file = filename or _get_indexes_filename(create_dir=True)
    with open(indexes_file, 'wb') as f:
        pickle.dump((cedict, cedict_char_to_idx, cedict_to_nids, nid_to_cedicts,
                     cedict_to_sentence_nids, sentence_nid_to_cedicts), f)


def load_indexes_from_file(filename=None):
    indexes_file = filename or _get_indexes_filename(create_dir=False)
    with open(indexes_file, 'rb') as f:
        (cedict, cedict_char_to_idx, cedict_to_nids, nid_to_cedicts,
         cedict_to_sentence_nids, sentence_nid_to_cedicts) = pickle.load(f)


def get_sentence_scores():
    search_str = "select max(reps-lapses), data from cards where nid=? group by nid"
    for sentence_nid, cedict_indices in sentence_nid_to_cedicts.items():
        for cedict_idx, hz_type, field_idx, char_idx in cedict_indices:
            pass

        reps_min_lapses, data = mw.col.db.all(search_str, nid)[0]
        strength = 10 if data == 'known' else reps_min_lapses
