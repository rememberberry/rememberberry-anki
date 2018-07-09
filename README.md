For debugging in anki
```
import importlib
from rememberberry import indexing
importlib.reload(indexing)
indexing.create_indexes(['all::chinese'], ['SpoonFedChinese'])
indexing.save_indexes_to_file()
indexing.load_indexes_from_file()
```
