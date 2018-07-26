For debugging in anki
```
from aqt import mw
import importlib
import rememberberry
from rememberberry import db
importlib.reload(db)
from rememberberry.db import RememberberryDatabase
rbd = RememberberryDatabase('rb.db')
rbd.create(['all::chinese'], ['SpoonFedChinese'])

rbd.update(['all::chinese'])
```
