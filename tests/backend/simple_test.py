"""
Simple inline test - copy and run this in a Python shell or as a script
"""

# Step 1: Check if psycopg2 is installed
print("Step 1: Checking psycopg2...")
try:
    import psycopg2
    print("✓ psycopg2 is installed")
except ImportError:
    print("✗ psycopg2 is NOT installed")
    print("  Run: pip install psycopg2-binary")
    exit(1)

# Step 2: Test connection string format
print("\nStep 2: Testing connection string...")
connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'
print(f"Connection string: {connection_string[:50]}...{connection_string[-20:]}")

# Step 3: Try to connect
print("\nStep 3: Attempting to connect...")
try:
    conn = psycopg2.connect(connection_string)
    print("✓ Successfully connected to Neon!")
    
    # Step 4: Get database info
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"✓ PostgreSQL version: {version[0][:50]}...")
    
    # Step 5: Check if table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'mob_geometries'
        );
    """)
    table_exists = cursor.fetchone()[0]
    
    if table_exists:
        print("✓ mob_geometries table exists")
        
        # Count rows
        cursor.execute("SELECT COUNT(*) FROM mob_geometries;")
        count = cursor.fetchone()[0]
        print(f"✓ Table contains {count} records")
    else:
        print("✗ mob_geometries table does NOT exist yet")
        print("  Run main.py to create it and insert data")
    
    cursor.close()
    conn.close()
    print("\n✓ All tests passed!")
    
except psycopg2.OperationalError as e:
    print(f"✗ Connection failed: {e}")
    print("  Check your connection string and internet connection")
except Exception as e:
    print(f"✗ Error: {e}")

