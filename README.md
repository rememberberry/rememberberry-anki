For debugging in anki
```
from aqt import mw
import importlib
import rememberberry
from rememberberry import db
importlib.reload(db)
from rememberberry.db import RememberberryDatabase
rbd = RememberberryDatabase('rb.db')
rbd.init(['all::chinese'], ['SpoonFedChinese'])

rbd.update(['all::chinese'])
```

To run tests
```
import importlib
import rememberberry
from rememberberry import test_db
importlib.reload(test_db)
test_db.run_tests()
```
