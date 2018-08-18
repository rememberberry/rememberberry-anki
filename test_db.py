import os
import shutil
from anki import Collection as aopen

import rememberberry
from rememberberry import db

def run_tests():
    col_filename = os.path.join(os.path.dirname(__file__), 'test_collection.anki2')
    tmp_filename = os.path.join(os.path.dirname(__file__), 'tmp.anki2')
    shutil.copy(col_filename, tmp_filename)
    col = aopen(tmp_filename)
    rbd = db.RememberberryDatabase('rb.db', col)
    rbd.init(['all::chinese'], ['SpoonFedChinese'])

    # Find an nid with an item which links to a sentence
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
    new, changed, parents = rbd.update(['all::chinese'])
    assert new == 0
    assert changed == 1
    assert parents == count
