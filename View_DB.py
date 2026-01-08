import sqlite3
import pandas as pd

# Connect to the DB
conn = sqlite3.connect('whale_watch.db')

# Read everything into a nice table
df = pd.read_sql_query("SELECT * FROM whales", conn)

# Show the goods
print(df)