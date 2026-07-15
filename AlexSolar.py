import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import numpy as np
from pvlib import location, irradiance
import datetime
import pytz

st.set_page_config(page_title="PV DinoHaus - Pure Modulleistung", layout="centered")

def check_password():
    if "password_correct" not in st.session_state:
        st.markdown("<h3 style='text-align: center;'>☀️ DinoHaus Login</h3>", unsafe_allow_html=True)
        pwd = st.text_input("Passwort:", type="password", key="final_pwd")
        if pwd == st.secrets.get("password", "admin"):
            st.session_state["password_correct"] = True
            st.rerun()
        return False
    return True

if not check_password(): 
    st.stop()

# --- SEITENLEISTE: DYNAMISCHE KONFIGURATION ---
st.sidebar.header("⚙️ Systemeinstellungen")

# 1. Globaler Effizienz-Regler (Kalibrierung)
REAL_WORLD_EFFICIENCY = st.sidebar.slider(
    "Globale Effizienz (Kalibrierung)", 
    min_value=0.1, 
    max_value=2.0, 
    value=0.88, 
    step=0.01,
    help="Skaliert den Gesamtertrag linear. Default = 0.88"
)

# 2. Anzahl der PV-Modulgruppen festlegen
num_configs = st.sidebar.number_input(
    "Anzahl der PV-Modulgruppen", 
    min_value=1, 
    max_value=10, 
    value=3, 
    step=1
)

# Standardwerte für eine schnelle Vorausfüllung
default_configs = [
    {"name": "Terrasse (Bifazial)", "wp": 880, "tilt": 30, "azi": 220, "color": "#f1c40f"},
    {"name": "Zaun S (Platte+Flex)", "wp": 640, "tilt": 90, "azi": 170, "color": "#e67e22"},
    {"name": "Zaun O (Flex)", "wp": 200, "tilt": 90, "azi": 80, "color": "#d35400"}
]

configs = []

# 3. Schleife zur Generierung der Eingabefelder für jede Gruppe
for i in range(int(num_configs)):
    st.sidebar.markdown(f"---")
    st.sidebar.subheader(f"Gruppe {i+1}")
    
    d_name = default_configs[i]["name"] if i < len(default_configs) else f"Anlage {i+1}"
    d_wp = default_configs[i]["wp"] if i < len(default_configs) else 400
    d_tilt = default_configs[i]["tilt"] if i < len(default_configs) else 35
    d_azi = default_configs[i]["azi"] if i < len(default_configs) else 180
    d_color = default_configs[i]["color"] if i < len(default_configs) else "#1f77b4"
    
    # Eingabemasken für den Nutzer
    name = st.sidebar.text_input(f"Name ({i+1})", value=d_name, key=f"name_{i}")
    wp = st.sidebar.number_input(f"Leistung in Wp ({i+1})", min_value=10, max_value=50000, value=d_wp, step=10, key=f"wp_{i}")
    tilt = st.sidebar.slider(f"Neigungswinkel [0°=flach, 90°=steil] ({i+1})", min_value=0, max_value=90, value=d_tilt, step=1, key=f"tilt_{i}")
    azi = st.sidebar.slider(f"Ausrichtung [0°=N, 90°=O, 180°=S, 270°=W] ({i+1})", min_value=0, max_value=360, value=d_azi, step=5, key=f"azi_{i}")
    color = st.sidebar.color_picker(f"Farbe im Chart ({i+1})", value=d_color, key=f"color_{i}")
    
    configs.append({
        "name": name,
        "wp": wp,
        "tilt": tilt,
        "azi": azi,
        "color": color
    })

# --- Wetterdaten abfragen ---
@st.cache_data(ttl=3600)
def get_weather(lat, lon, date):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&hourly=cloudcover,direct_radiation,diffuse_radiation&start_date={date}&end_date={date}&timezone=Europe%2FBerlin")
    try:
        res = requests.get(url).json()
        return pd.DataFrame({
            'cloud': res['hourly']['cloudcover'],
            'direct': res['hourly']['direct_radiation'],
            'diffuse': res['hourly']['diffuse_radiation']
        })
    except: 
        return None

# --- Hauptbereich der App ---
DATE_SEL = st.date_input("Prognose-Tag", datetime.date.today())

if DATE_SEL:
    weather = get_weather(49.644, 8.354, DATE_SEL)
    
    if weather is not None:
        tz = pytz.timezone('Europe/Berlin')
        times = pd.date_range(start=pd.Timestamp(DATE_SEL).tz_localize(tz), periods=24, freq='h')
        
        site = location.Location(49.644, 8.354, tz='Europe/Berlin')
        solpos = site.get_solarposition(times)

        results = {}
        for mod in configs:
            direct = weather['direct'].values
            diffuse = weather['diffuse'].values
            
            # Geometrische Berechnung mit pvlib
            aoi = irradiance.aoi(mod['tilt'], mod['azi'], solpos['zenith'], solpos['azimuth'])
            
            # Mindestaufnahme für die Reflexionen / Albedo-Effekt
            exposure = np.maximum(np.cos(np.radians(aoi)), 0.4) 
            
            # Berechnung der ungekürzten Modulleistung in kW (ohne Wechselrichter-Limit)
            power_kw = ((direct * exposure + diffuse) / 1000) * (mod['wp'] / 1000) * (REAL_WORLD_EFFICIENCY * 4.2)
            
            results[mod['name']] = power_kw

        df = pd.DataFrame(results, index=times)
        df[solpos['elevation'] < 2] = 0 # Nachts auf 0 setzen
        
        total_yield = df.sum().sum()

        st.markdown(f"## 📊 Reine Modul-Prognose (ungedeckelt): **{total_yield:.2f} kWh**")
        
        # Plotly Graph erstellen
        fig = go.Figure()
        for mod in configs:
            fig.add_trace(go.Scatter(
                x=df.index, 
                y=df[mod['name']], 
                name=mod['name'], 
                stackgroup='one', 
                fill='tonexty',
                line=dict(color=mod['color'])
            ))

        # Dynamisches Skalieren des Y-Achsen-Maximums basierend auf der tatsächlichen Peak-Leistung im Datensatz
        max_power_produced = df.sum(axis=1).max()
        y_max = max(1.5, max_power_produced * 1.1)  # Bietet etwas Headroom nach oben

        fig.update_layout(
            template="plotly_dark", 
            yaxis=dict(title="kW", range=[0, y_max]), 
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("Wetterdaten konnten nicht geladen werden. Bitte versuche es später noch einmal.")
