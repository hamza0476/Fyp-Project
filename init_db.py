import sqlite3

conn = sqlite3.connect('users.db')
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        profile_pic TEXT
    )
''')

conn.commit()
conn.close()

print("Database and table created successfully!")
