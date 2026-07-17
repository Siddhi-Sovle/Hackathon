import requests
import pandas as pd
import zipfile
import io
from datetime import datetime
import schedule
import time
import os

SAVE_FOLDER = r"C:\Users\apoor\Downloads\dataset\gdelt_outputs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


# yeh code is to fetch live gdelt data
def fetch_gdelt():

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching GDELT...")

    master_url = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"

    response = requests.get(master_url)

    lines = response.text.strip().split('\n')

    recent = lines[-24:]      # last 6 hours

    all_dfs = []

    for line in recent:

        parts = line.strip().split(' ')

        if len(parts) < 3 or 'export' not in parts[2]:
            continue

        try:
            r = requests.get(parts[2], timeout=30)

            z = zipfile.ZipFile(io.BytesIO(r.content))

            df_temp = pd.read_csv(
                z.open(z.namelist()[0]),
                sep='\t',
                header=None,
                on_bad_lines='skip'
            )

            all_dfs.append(df_temp)

        except Exception as e:
            print(f"Failed: {e}")

    if not all_dfs:
        print("No GDELT data fetched.")
        return None

    df = pd.concat(all_dfs, ignore_index=True)

    print(f"Fetched {len(df)} rows")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    raw_path = os.path.join(
        SAVE_FOLDER,
        f"gdelt_raw_{timestamp}.csv"
    )

    df.to_csv(raw_path, index=False)

    print(f"Raw file saved: {raw_path}")

    return df


#cleaning and processing iss code mein krenge 
def process_gdelt(df):

    df.columns = range(len(df.columns))

    events_columns = {
        1:  'SQLDATE',
        5:  'Actor1Name',
        15: 'Actor2Name',
        26: 'EventCode',
        30: 'GoldsteinScale',
        31: 'NumMentions',
        34: 'AvgTone',
        53: 'ActionGeo_FullName',
        54: 'ActionGeo_CountryCode',
        55: 'ActionGeo_Lat',
        56: 'ActionGeo_Long',
        60: 'SOURCEURL'
    }

    df_events = df[list(events_columns.keys())].copy()
    df_events.columns = list(events_columns.values())

    df_events['EventCode'] = df_events['EventCode'].astype(str)

    df_events['GoldsteinScale'] = pd.to_numeric(
        df_events['GoldsteinScale'],
        errors='coerce'
    )

    CONFLICT_CODES = [
        '14','15','17','18','19','20'
    ]

    OIL_COUNTRIES = [
        'SA','IR','IQ','AE','KW',
        'RU','NG','LY','YE','EG'
    ]

    energy_events = df_events[
        (df_events['ActionGeo_CountryCode'].str[:2].isin(OIL_COUNTRIES))
        &
        (df_events['EventCode'].str[:2].isin(CONFLICT_CODES))
        &
        (df_events['GoldsteinScale'] < -2)
    ].copy()

    energy_events["SQLDATE"] = pd.to_numeric(
        energy_events["SQLDATE"],
        errors="coerce"
    ).astype(str).str[:8]

    energy_events["SQLDATE"] = pd.to_datetime(
        energy_events["SQLDATE"]
    )
    
    energy_events['ActionGeo_Lat'] = pd.to_numeric(
        energy_events['ActionGeo_Lat'],
        errors='coerce'
    ) / 1000

    energy_events['ActionGeo_Long'] = pd.to_numeric(
        energy_events['ActionGeo_Long'],
        errors='coerce'
    )

    energy_events = energy_events.dropna(
        subset=[
            'ActionGeo_Lat',
            'ActionGeo_Long'
        ]
    ).copy()

    energy_events['Actor1Name'] = (
        energy_events['Actor1Name']
        .fillna("Unknown")
    )

    energy_events['Actor2Name'] = (
        energy_events['Actor2Name']
        .fillna("Unknown")
    )

    def severity(x):
        if pd.isna(x):
            return "Unknown"
        elif x <= -8:
            return "Critical"
        elif x <= -4:
            return "High"
        elif x < 0:
            return "Medium"
        else:
            return "Low"

    energy_events["severity"] = (
        energy_events["GoldsteinScale"]
        .apply(severity)
    )

    energy_events["event_weight"] = (
        energy_events["GoldsteinScale"]
        .abs()
    )
    energy_events["event_id"] = range(1, len(energy_events) + 1)
    energy_events = (
        energy_events
        .drop_duplicates(
            subset=['SOURCEURL'], keep='first'
        )
        .reset_index(drop=True)
    )

    energy_events['event_id'] = range(
        1,
        len(energy_events)+1
    )

    return energy_events

# Combined scoring function

def add_relevance_score(energy_events, threshold=5):

    ENERGY_KEYWORDS = [
        'oil', 'crude', 'petroleum', 'tanker',
        'pipeline', 'refinery', 'energy', 'gas',
        'fuel', 'opec', 'barrel', 'brent'
    ]

    MARITIME_KEYWORDS = [
        'port', 'harbor', 'harbour', 'shipping',
        'vessel', 'ship', 'cargo', 'terminal',
        'dock', 'maritime', 'strait'
    ]

    STRATEGIC_LOCATIONS = [
        'hormuz', 'suez', 'red sea', 'gulf',
        'chabahar', 'bandar', 'abbas', 'bushehr',
        'kharg', 'bab', 'mandeb', 'malacca',
        'persian'
    ]

    CONFLICT_KEYWORDS = [
        'attack', 'strike', 'missile', 'war',
        'military', 'bomb', 'explosion', 'sanction',
        'embargo', 'conflict', 'nuclear'
    ]

    ENERGY_ACTORS = [
        'IRN', 'IRNMIL', 'IRNGOV',
        'SAU', 'SAUMIL',
        'USA', 'USAMIL',
        'ISR', 'ISRMIL',
        'RUS',
        'YEMMIL',
        'MIL', 'GOV', 'BUS'
    ]

    IMPORTANT_COUNTRIES = [
        'IR', 'SA', 'AE', 'IQ', 'KW',
        'YE', 'EG', 'NG', 'LY'
    ]

    def calculate_relevance_score(row):

        score = 0

        url = str(row['SOURCEURL']).lower()

        actor1 = str(row['Actor1Name']).upper()
        actor2 = str(row['Actor2Name']).upper()

        country = str(
            row['ActionGeo_CountryCode']
        )[:2]

        # URL scoring
        score += sum(
            k in url for k in ENERGY_KEYWORDS
        ) * 3

        score += sum(
            k in url for k in STRATEGIC_LOCATIONS
        ) * 4

        score += sum(
            k in url for k in MARITIME_KEYWORDS
        ) * 2

        score += sum(
            k in url for k in CONFLICT_KEYWORDS
        ) * 2

        # Actor scoring
        if any(a in actor1 for a in ENERGY_ACTORS):
            score += 2

        if any(a in actor2 for a in ENERGY_ACTORS):
            score += 2

        # Country scoring
        if country in IMPORTANT_COUNTRIES:
            score += 1

        # Severity scoring
        if row['GoldsteinScale'] <= -8:
            score += 2

        elif row['GoldsteinScale'] <= -5:
            score += 1

        return score

    # Calculate scores
    energy_events = energy_events.copy()

    energy_events['relevance_score'] = (
        energy_events.apply(
            calculate_relevance_score,
            axis=1
        )
    )

    print("\nScore distribution:")
    print(
        energy_events['relevance_score']
        .value_counts()
        .sort_index()
    )

    # Filter
    energy_events_filtered = (
        energy_events[
            energy_events['relevance_score']
            >= threshold
        ]
        .copy()
        .reset_index(drop=True)
    )

    energy_events_filtered['event_id'] = range(
        1,
        len(energy_events_filtered) + 1
    )

    print(
        f"\nAfter filter: "
        f"{len(energy_events_filtered)} events"
    )

    return energy_events_filtered

def run_gdelt_pipeline():

    df_raw = fetch_gdelt()

    if df_raw is None:
        return

    energy_events = process_gdelt(df_raw)

    energy_events_filtered = add_relevance_score(
        energy_events
    )

    energy_events_filtered.to_csv(
        os.path.join(
            SAVE_FOLDER,
            "gdelt_clean_latest.csv"
        ),
        index=False
    )

    print(
        f"Final filtered events: "
        f"{len(energy_events_filtered)}"
    )
    return energy_events_filtered

if __name__ == "__main__":

    # Run immediately
    run_gdelt_pipeline()

    # Schedule every 6 hours
    schedule.every(6).hours.do(run_gdelt_pipeline)

    print("\nWaiting for next run...")

    while True:
        schedule.run_pending()
        time.sleep(60)