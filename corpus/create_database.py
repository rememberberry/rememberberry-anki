import sys
import sqlite3

if __name__ == '__main__':
    filename = sys.argv[1]
    db = sqlite3.connect(filename)
    cursor = db.cursor()
    cursor.execute('''
        CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT,
                           phone TEXT, email TEXT unique, password TEXT)
    ''')
    db.commit()
    db.close()
    
