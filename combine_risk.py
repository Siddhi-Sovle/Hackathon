import requests
import sqlite3
from datetime import datetime
import pandas as pd
import numpy as np

df_gdelt = pd.read_csv(
    r"C:\Users\apoor\Downloads\dataset\risk_scoring\gdelt_outputs\gdelt_clean_latest.csv"
)


# ── Step 1: Load PortWatch data from SQLite ───────────────────
def load_portwatch_from_db():
    conn = sqlite3.connect('events.db')
    df_portwatch_live = pd.read_sql_query(
        "SELECT * FROM events WHERE source = 'ais'", 
        conn
    )
    conn.close()
    
    print(f"PortWatch records in DB: {len(df_portwatch_live)}")
    print(df_portwatch_live[['corridor', 'severity', 
                              'supply_drop_pct', 
                              'timestamp']].to_string())
    return df_portwatch_live

df_portwatch_live = load_portwatch_from_db()

# ── Step 2: Map chokepoint names to coordinates ───────────────
# So we can connect GDELT lat/lon to corridor names
CHOKEPOINT_COORDS = {
    "Strait of Hormuz"   : {'lat': 26.30, 'lon': 56.86},
    "Bab el-Mandeb Strait"      : {'lat': 12.79, 'lon': 43.35},
    "US Gulf Coast Route": {'lat': 21.00, 'lon': -86.00},
    # Add these even if not in PortWatch — for completeness
    "Suez Canal"         : {'lat': 30.59, 'lon': 32.44},
    "Bosporus Strait"    : {'lat': 41.17, 'lon': 29.09},
    "Malacca Strait"     : {'lat':  1.52, 'lon': 102.67},
}

# ── Step 3: Distance function ─────────────────────────────────
def calculate_distance_km(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, 
                                  [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (np.sin(dlat/2)**2 + 
         np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2)
    return R * 2 * np.arcsin(np.sqrt(a))

# ── Step 4: Map each GDELT event to nearest chokepoint ────────
def map_event_to_chokepoint(event_lat, event_lon, 
                              radius_km=1000):
    nearest_name = None
    nearest_dist = float('inf')
    
    for name, coords in CHOKEPOINT_COORDS.items():
        dist = calculate_distance_km(
            event_lat, event_lon,
            coords['lat'], coords['lon']
        )
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_name = name
    
    # Only return if within radius
    if nearest_dist <= radius_km:
        return nearest_name, round(nearest_dist, 1)
    return None, None

# ── Step 5: Apply to all GDELT events ────────────────────────
gdelt_with_chokepoint = []

for _, row in df_gdelt.iterrows():
    
    chokepoint, dist = map_event_to_chokepoint(
        row['ActionGeo_Lat'],
        row['ActionGeo_Long']
    )
    
    if chokepoint:
        row_copy = row.copy()
        row_copy['nearest_chokepoint'] = chokepoint
        row_copy['distance_km']        = dist
        gdelt_with_chokepoint.append(row_copy)

df_gdelt_mapped = pd.DataFrame(
    gdelt_with_chokepoint
).reset_index(drop=True)

print(f"\nGDELT events mapped to chokepoints: {len(df_gdelt_mapped)}")
print(df_gdelt_mapped[['Actor1Name', 'Actor2Name',
                         'GoldsteinScale',
                         'nearest_chokepoint',
                         'distance_km']].to_string())

# ── Step 6: Join GDELT with PortWatch on corridor name ────────
df_combined = pd.merge(
    df_gdelt_mapped,
    df_portwatch_live[['corridor', 'severity', 
                        'supply_drop_pct', 'description']],
    left_on  = 'nearest_chokepoint',
    right_on = 'corridor',
    how      = 'left'
)
# print(df_combined.columns.tolist())
# Rename columns for clarity
df_combined = df_combined.rename(columns={
    'severity_x': 'gdelt_severity',
    'severity_y': 'portwatch_severity',
    'supply_drop_pct': 'portwatch_supply_drop'
})

# print(f"\nCombined dataset: {len(df_combined)} rows")
# print(
#     df_combined[
#         [
#             'Actor1Name',
#             'nearest_chokepoint',
#             'GoldsteinScale',
#             'event_weight',
#             'portwatch_severity',
#             'portwatch_supply_drop'
#         ]
#     ].to_string()
# )
# print(
#     df_gdelt[
#         [
#             'ActionGeo_FullName',
#             'ActionGeo_Lat',
#             'ActionGeo_Long'
#         ]
#     ]
#     .head(20)
#     .to_string()
# )

# print(
#     df_gdelt[
#         [
#             'ActionGeo_FullName',
#             'ActionGeo_CountryCode',
#             'ActionGeo_Lat',
#             'ActionGeo_Long'
#         ]
#     ].head(30)
# )
print(df_gdelt['ActionGeo_Lat'].min())
print(df_gdelt['ActionGeo_Lat'].max())

print(df_gdelt['ActionGeo_Long'].min())
print(df_gdelt['ActionGeo_Long'].max())