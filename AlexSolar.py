import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import numpy as np
from pvlib import location, irradiance
import datetime
import pytz

# --- MANUELLE KALIBRIERUNG (DEIN REGLER) ---
# Wir setzen die Effizienz so, dass 1,7kWp bei Sonne ~5,1kWh liefern.
# Wenn es immer noch nicht passt, drehe NUR an diesem einen Wert:
REAL_WORLD_EFFICIENCY = 0.88 

st.set_page_config(page_title="PV Alex", layout="centered")

def check_password():
    if "password_correct" not in st.session_state:
        st.markdown("<h3 style='text-align: center;'>☀️ DinoHaus Login</h3>", unsafe_allow_html=True)
        pwd = st.text_input("Passwort:", type="password", key="final_pwd")
        if pwd == st.secrets.get("password", "admin"):
            st.session_state["password_correct"] = True
            st.rerun()
        return False
    return True

if not check_password(): st.stop()

# Deine Hardware-Konfiguration
configs = [
    {"name": "Balkon (Bifazial)", "wp": 900, "tilt": 90, "azi": 185, "color": "#f1c40f", "max": 0.80},
   # {"name": "Zaun S (Platte+Flex)", "wp": 640, "tilt": 90, "azi": 170, "color": "#e67e22", "max": 0.60},
     #{"name": "Zaun O (Flex)", "wp": 200, "tilt": 90, "azi": 80, "color": "#d35400", "max": 0.20}
]

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
    except: return None

DATE_SEL = st.date_input("Prognose-Tag", datetime.date.today())

if DATE_SEL:
    weather = get_weather(49.482869333, 8.2741404808, DATE_SEL)
    tz = pytz.timezone('Europe/Berlin')
    times = pd.date_range(start=pd.Timestamp(DATE_SEL).tz_localize(tz), periods=24, freq='h')
    
    site = location.Location(49.482869333, 8.2741404808, tz='Europe/Berlin')
    solpos = site.get_solarposition(times)

    results = {}
    for mod in configs:
        # Wir nutzen die Globalstrahlung der API als Basis
        # und wenden einen aggressiven Korrekturfaktor an.
        direct = weather['direct'].values
        diffuse = weather['diffuse'].values
        
        # Geometrische Berechnung
        aoi = irradiance.aoi(mod['tilt'], mod['azi'], solpos['zenith'], solpos['azimuth'])
        # Wir erzwingen eine Mindestaufnahme für die bifazialen Reflexionen
        exposure = np.maximum(np.cos(np.radians(aoi)), 0.4) 
        
        # Berechnung der Leistung in kW
        # Die Formel ist nun linear auf deine Erträge (bis 5.1 kWh) skaliert
        power_kw = ((direct * exposure + diffuse) / 1000) * (mod['wp'] / 1000) * (REAL_WORLD_EFFICIENCY * 4.2)
        
        # Hardware-Deckelung
        results[mod['name']] = np.minimum(power_kw, mod['max'])

    df = pd.DataFrame(results, index=times)
    df[solpos['elevation'] < 2] = 0 # Nachts aus
    
    total_yield = df.sum().sum()

    st.markdown(f"## 📊 Prognose: **{total_yield:.2f} kWh**")
    
    fig = go.Figure()
    for mod in configs:
        fig.add_trace(go.Scatter(x=df.index, y=df[mod['name']], name=mod['name'], stackgroup='one', fill='tonexty'))

    fig.update_layout(template="plotly_dark", yaxis=dict(title="kW", range=[0, 1.5]), margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)