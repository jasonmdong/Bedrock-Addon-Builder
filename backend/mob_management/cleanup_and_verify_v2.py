"""
Clean up test data and prepare for main mob insertion
Writes output to file for verification
"""

import psycopg2

connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'

output = []

try:
    conn = psycopg2.connect(connection_string)
    cursor = conn.cursor()

    output.append("Cleaning up test data...")
    cursor.execute("DELETE FROM mob_geometries WHERE mob_name = 'test_mob';")
    conn.commit()

    # Verify cleanup
    cursor.execute("SELECT COUNT(*) FROM mob_geometries;")
    count = cursor.fetchone()[0]
    output.append(f"✓ Test data cleaned up")
    output.append(f"✓ Table now contains {count} records")

    # Show table structure
    output.append("\nTable structure:")
    cursor.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'mob_geometries'
        ORDER BY ordinal_position;
    """)

    output.append(f"\n{'Column Name':<25} {'Data Type':<20}")
    output.append("-" * 45)
    for column_name, data_type in cursor.fetchall():
        output.append(f"{column_name:<25} {data_type:<20}")

    cursor.close()
    conn.close()

    output.append("\n✓ Database is clean and ready for mob data insertion!")
    output.append("✓ Run 'python main.py' to insert all 160+ mobs")

except Exception as e:
    output.append(f"✗ Error: {e}")
    import traceback
    output.append(traceback.format_exc())

# Print to console
for line in output:
    print(line)

# Also write to file
with open('cleanup_results.txt', 'w') as f:
    f.write('\n'.join(output))

print("\nResults also saved to cleanup_results.txt")

