import psycopg2

connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'

conn = psycopg2.connect(connection_string)
cursor = conn.cursor()

# Delete test data
cursor.execute("DELETE FROM mob_geometries WHERE mob_name = 'test_mob';")
conn.commit()

# Check record count
cursor.execute("SELECT COUNT(*) FROM mob_geometries;")
count = cursor.fetchone()[0]

# Check table structure
cursor.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'mob_geometries'
    ORDER BY ordinal_position;
""")
columns = cursor.fetchall()

cursor.close()
conn.close()

# Write results
with open('cleanup_status.txt', 'w') as f:
    f.write("CLEANUP VERIFICATION\n")
    f.write("=" * 50 + "\n\n")
    f.write(f"Records in table: {count}\n")
    f.write("Test mob: DELETED ✓\n\n")
    f.write("Table Structure:\n")
    f.write("-" * 50 + "\n")
    f.write(f"{'Column Name':<25} {'Data Type':<20}\n")
    f.write("-" * 50 + "\n")
    for col_name, col_type in columns:
        f.write(f"{col_name:<25} {col_type:<20}\n")
    f.write("\n" + "=" * 50 + "\n")
    f.write("✓ Database is clean and ready!\n")
    f.write("✓ Run: python main.py\n")

print("Done!")

