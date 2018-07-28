import os
from anki import Collection as aopen

import rememberberry
from rememberberry import db

def run_tests():
    col_filename = os.path.join(os.path.dirname(__file__), 'test_collection.anki2')
    print(col_filename)
    col = aopen(col_filename)
    rbd = db.RememberberryDatabase('rb.db', col)
    rbd.init(['all::chinese'], ['SpoonFedChinese'])
#
    #rbd.update(['all::chinese'])
