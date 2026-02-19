"""
Clean up test data and prepare for main mob insertion
"""

import psycopg2

connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'

try:
    conn = psycopg2.connect(connection_string)
    cursor = conn.cursor()

    print("Cleaning up test data...")
    cursor.execute("DELETE FROM mob_geometries WHERE mob_name = 'test_mob';")
    conn.commit()

    # Verify cleanup
    cursor.execute("SELECT COUNT(*) FROM mob_geometries;")
    count = cursor.fetchone()[0]
    print(f"✓ Test data cleaned up")
    print(f"✓ Table now contains {count} records")

    # Show table structure
    print("\nTable structure:")
    cursor.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'mob_geometries'
        ORDER BY ordinal_position;
    """)

    print(f"\n{'Column Name':<25} {'Data Type':<20}")
    print("-" * 45)
    for column_name, data_type in cursor.fetchall():
        print(f"{column_name:<25} {data_type:<20}")

    cursor.close()
    conn.close()

    print("\n✓ Database is clean and ready for mob data insertion!")
    print("✓ Run 'python main.py' to insert all 160+ mobs")

except Exception as e:
    print(f"✗ Error: {e}")

