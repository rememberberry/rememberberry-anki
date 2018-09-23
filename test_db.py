import os
import shutil
from anki import Collection as aopen

import rememberberry
from rememberberry import db
from time import time

def run_tests():
    col_filename = os.path.join(os.path.dirname(__file__), 'test_collection.anki2')
    tmp_filename = os.path.join(os.path.dirname(__file__), 'tmp.anki2')
    shutil.copy(col_filename, tmp_filename)
    col = aopen(tmp_filename)
    rbd = db.RememberberryDatabase('rb.db', col, completed_hsk_lvl=4)
    t0 = time()
    rbd.init(['all::chinese'], ['SpoonFedChinese'])
    t1 = time()
    print('Initialization took %f s' % (t1-t0))

    # Find an nid with several items which links to it
    rbd.attach()
    c = rbd._get_cursor()
    c.execute('''
        SELECT nid, from_hash, to_hash, COUNT(*) FROM rb.item_links
        JOIN rb.note_links ON to_hash=hash
        GROUP BY to_hash
        HAVING COUNT(*) > 1
    ''')
    res = c.fetchone()
    nid, form_hash, to_hash, count = res

    # Update the reps parameter
    c.execute('''
        UPDATE cards SET reps=reps+1 WHERE nid=?
    ''', (nid,))

    # Update the rememberberry database
    t0 = time()
    new, changed, parents = rbd.update(['all::chinese'])
    t1 = time()
    print('Update took %f s' % (t1-t0))

    # Make sure the item corresponding to the card was updated, and all sentences
    assert new == 0
    assert changed == 1
    assert parents == count
    
    items, item_words = rbd.search(limit=10, num_unknown=1)
    for i in range(10):
        print(items[i], item_words[i])
        print('=================')
