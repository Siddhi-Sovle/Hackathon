import requests
import sqlite3
from datetime import datetime
import pandas as pd

# Confirmed via fetch_chokepoint_list.py against PortWatch's real 28-chokepoint list
PORTWATCH_CHOKEPOINTS = {
    "Suez Canal": "chokepoint1",
    "Bosporus Strait": "chokepoint3",
    "Bab el-Mandeb Strait": "chokepoint4",
    "Malacca Strait": "chokepoint5",
    "Strait of Hormuz": "chokepoint6",
    "US Gulf Coast Route": "chokepoint22"
}

BASE_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"


# def ensure_supply_drop_column():
#     """Adds a supply_drop_pct column if it doesn't already exist."""
#     conn = sqlite3.connect('events.db')
#     try:
#         conn.execute("ALTER TABLE events ADD COLUMN supply_drop_pct REAL")
#         conn.commit()
#     except sqlite3.OperationalError:
#         pass  # column already exists
#     conn.close()


def fetch_portwatch_data(portid, num_recent_records=14):
    params = {
        "where": f"portid='{portid}'",
        "outFields": "*",
        "f": "json",
        "orderByFields": "date DESC",
        "resultRecordCount": num_recent_records
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        features = data.get("features", [])
        return [f["attributes"] for f in features]
    except Exception as e:
        print(f"PortWatch request failed for '{portid}': {e}")
        return []

def save_raw_portwatch_data(
    corridor_name,
    portid,
    records
):
    conn = sqlite3.connect('events.db')

    conn.execute("""
        CREATE TABLE IF NOT EXISTS portwatch_raw (

            corridor TEXT,
            portid TEXT,
            date TEXT,

            n_tanker INTEGER,
            n_total INTEGER,

            capacity_tanker REAL,
            capacity REAL,

            timestamp TEXT,

            UNIQUE(corridor, date)
        )
    """)

    for row in records:

        conn.execute(
            """
            INSERT OR IGNORE INTO portwatch_raw (
                corridor,
                portid,
                date,
                n_tanker,
                n_total,
                capacity_tanker,
                capacity,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                corridor_name,
                portid,
                str(row.get("date")),

                row.get("n_tanker"),
                row.get("n_total"),

                row.get("capacity_tanker"),
                row.get("capacity"),

                datetime.now().isoformat()
            )
        )

    conn.commit()
    conn.close()
    
def calculate_tanker_severity(records):
    if len(records) < 2:
        return 0.1, 0.0, "Not enough data", None  # added None for date

    latest = records[0]
    previous = records[1:]

    latest_tankers = latest.get("n_tanker", 0) or 0
    avg_previous = sum((r.get("n_tanker", 0) or 0) for r in previous) / len(previous)
    latest_date = latest.get("date", "unknown")  # extract date here

    if avg_previous == 0:
        return 0.1, 0.0, "No baseline tanker data", latest_date

    percent_drop = round(((avg_previous - latest_tankers) / avg_previous) * 100, 1)
    severity = round(min(max(percent_drop / 20, 0), 1.0), 2)

    direction_text = (f"DOWN {percent_drop:.1f}%" if percent_drop > 0 
                      else f"UP {abs(percent_drop):.1f}%" if percent_drop < 0 
                      else "UNCHANGED")

    description = (f"As of {latest_date}: {latest_tankers} tankers vs "
                   f"{avg_previous:.1f} avg. Traffic {direction_text}")

    return severity, percent_drop, description, latest_date  # return date


def run_portwatch_ingestion():
    for corridor_name, portid in PORTWATCH_CHOKEPOINTS.items():
        records = fetch_portwatch_data(portid)
        if records:
            save_raw_portwatch_data(
                corridor_name,
                portid,
                records
            )

            severity, supply_drop_pct, description, latest_date = \
                calculate_tanker_severity(records)

            save_event(
                "ais",
                corridor_name,
                description,
                severity,
                supply_drop_pct,
                latest_date
            )
        else:
            print(f"No PortWatch data returned for {corridor_name}")

def save_event(source, corridor, description, severity, supply_drop_pct, latest_date):
    conn = sqlite3.connect('events.db')
    
    # Create table with unique constraint on corridor + date
    conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            source TEXT,
            corridor TEXT,
            timestamp TEXT,
            description TEXT,
            severity REAL,
            supply_drop_pct REAL,
            data_date TEXT,
            UNIQUE(corridor, data_date)  -- prevents duplicates
        )
    ''')
    
    try:
        conn.execute(
            """INSERT OR IGNORE INTO events 
               (source, corridor, timestamp, description, 
                severity, supply_drop_pct, data_date) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (source, corridor, datetime.now().isoformat(), 
             description, severity, supply_drop_pct, str(latest_date))
        )
        conn.commit()
        
        if conn.total_changes > 0:
            print(f"✅ Saved new: {corridor} — {latest_date}")
        else:
            print(f"⏭  Skipped duplicate: {corridor} — {latest_date} already exists")
            
    except Exception as e:
        print(f"❌ DB error: {e}")
    finally:
        conn.close()




if __name__ == "__main__":
    # PortWatch updates weekly (Tuesdays), so we don't need a tight 15-min
    # loop like GDELT/prices — checking once every 24 hours is more than
    # enough to catch the weekly refresh whenever it happens, without you
    # needing to manually remember to re-run this.
    import time
    # ensure_supply_drop_column()
    while True:
        run_portwatch_ingestion()
        print("Sleeping 24 hours before next PortWatch check...")
        time.sleep(86400)  # 24 hours




# siddhi yahan se jo aage ke codes hain woh sirf data check krne ke liye hain is liye unko rkhe rehna futuremein check krne ke liye ki kaisa chal rha hai 



#1. check what table exists in your db
# import sqlite3
# import pandas as pd

# conn = sqlite3.connect("events.db")

# tables = pd.read_sql_query(
#     """
#     SELECT name
#     FROM sqlite_master
#     WHERE type='table'
#     """,
#     conn
# )

# conn.close()

# print(tables)

#2. check the processed portwatch data(events)

# conn = sqlite3.connect("events.db")

# df_events = pd.read_sql_query(
#     "SELECT * FROM events",
#     conn
# )

# conn.close()

# print(df_events.shape)
# print(df_events.head())


#3. Check the raw PortWatch data (portwatch_raw)


# conn = sqlite3.connect("events.db")

# df_raw = pd.read_sql_query(
#     "SELECT * FROM portwatch_raw",
#     conn
# )

# conn.close()

# print(df_raw.shape)
# print(df_raw.head())



# 4. sanity check 


# conn = sqlite3.connect("events.db")

# print("Events:")
# print(pd.read_sql_query(
#     "SELECT corridor, severity, supply_drop_pct FROM events",
#     conn
# ))

# print("\nRaw counts:")
# print(pd.read_sql_query(
#     """
#     SELECT corridor, COUNT(*) as rows
#     FROM portwatch_raw
#     GROUP BY corridor
#     """,
#     conn
# ))

# conn.close()