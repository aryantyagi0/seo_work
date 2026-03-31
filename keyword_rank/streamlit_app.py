import streamlit as st
import requests
import subprocess
import time
import pandas as pd
from database import init_db, save_result, get_keyword_history
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="requests")

# Initialize session state and database
if 'backend_ready' not in st.session_state:
    st.session_state.backend_ready = False
if 'backend_process' not in st.session_state:
    st.session_state.backend_process = None

init_db()

def start_backend():
    """Reliably auto-start FastAPI backend with health checks."""
    if st.session_state.backend_ready:
        return True
        
    def health_check():
        max_retries = 12
        for i in range(max_retries):
            try:
                response = requests.get("http://127.0.0.1:8001/health", timeout=2)
                if response.status_code == 200:
                    st.session_state.backend_ready = True
                    return True
            except:
                pass
            time.sleep(1)
        return False
    
    # Kill existing backend processes
    try:
        subprocess.run(["lsof", "-ti:8001"], capture_output=True, check=False)
        subprocess.run(["pkill", "-f", "uvicorn.*8001"], capture_output=True, check=False)
        time.sleep(1)
    except:
        pass
    
    # Start backend subprocess
    try:
        process = subprocess.Popen([
            "uvicorn", "backend.api:app", 
            "--port", "8001", 
            "--host", "127.0.0.1",
            "--log-level", "error"
        ])
        st.session_state.backend_process = process
    except Exception as e:
        st.error(f"Failed to start backend: {e}")
        return False
    
    return health_check()

def kill_backend():
    """Clean up backend process."""
    if st.session_state.backend_process:
        try:
            st.session_state.backend_process.terminate()
            st.session_state.backend_process.wait(timeout=3)
        except:
            pass
        st.session_state.backend_process = None

# Auto-start backend
if not st.session_state.backend_ready:
    with st.spinner("🚀 Starting backend server..."):
        start_backend()

st.set_page_config(page_title="SEO Rank Tracker", layout="wide")
st.title("🔍 Local SEO Rank Tracker")

# Backend status
if st.session_state.backend_ready:
    st.sidebar.success("✅ Backend Connected")
else:
    st.sidebar.error("❌ Backend Starting...")
    st.sidebar.info("Wait 10 seconds then refresh")

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Settings")
    
    cities_dict = {
        "Ahmedabad": (23.0225, 72.5714),
        "Bangalore": (12.9716, 77.5946),
        "Chennai": (13.0827, 80.2707),
        "Delhi": (28.6139, 77.2090),
        "Gurugram": (28.4595, 77.0266),
        "Hyderabad": (17.3850, 78.4867),
        "Jaipur": (26.9124, 75.7873),
        "Kolkata": (22.5726, 88.3639),
        "Lucknow": (26.8467, 80.9462),
        "Mumbai": (19.0760, 72.8777),
        "Noida": (28.5355, 77.3910),
        "Pune": (18.5204, 73.8567)
    }
    
    city = st.selectbox("🏙️ Select City", sorted(list(cities_dict.keys())))
    area = st.text_input("📍 Area", "Sector 62")
    brand = st.text_input("🏢 Brand Name", value="Anytime Fitness")
    domain = st.text_input("🌐 Domain", value="anytimefitness.co.in")
    
    method = st.radio("🔍 Search Engine", ["playwright", "serpapi"])
    
    # ✅ FIXED: Use widget key directly - NO session_state conflict
    serp_api_key = None
    if method == "serpapi":
        serp_api_key = st.text_input("🔑 SerpApi Key", type="password", key="serpapi_key")
        if not serp_api_key:
            st.warning("⚠️ Enter API key for SerpApi")

keyword = st.text_input("🔎 Enter Keyword (e.g., gym)")

if keyword:
    area_str = f"{area} " if area else ""
    final_keyword = f"{keyword} in {area_str}{city}"
    st.info(f"🔍 **Searching for:** `{final_keyword}`")

# Check Rankings Button
if st.button("🚀 Check Rankings", type="primary", disabled=not st.session_state.backend_ready):
    if not st.session_state.backend_ready:
        st.error("⏳ Backend not ready. Please wait or refresh.")
    elif not brand or not domain:
        st.error("❌ Please provide Brand Name and Domain.")
    elif method == "serpapi" and not serp_api_key:
        st.error("❌ SerpApi Key required.")
    else:
        lat, lng = cities_dict[city]
        payload = {
            "keyword": final_keyword, 
            "brand": brand, 
            "domain": domain,
            "method": method, 
            "latitude": lat, 
            "longitude": lng,
            "city": city, 
            "area": area,
            "api_key": serp_api_key  # ✅ Always defined, None for playwright
        }

        with st.spinner("📊 Fetching Google Results..."):
            try:
                response = requests.post("http://127.0.0.1:8001/rank", json=payload, timeout=45)
                results = response.json()

                if "error" in results:
                    st.error(f"❌ {results['error']}")
                else:
                    st.success("✅ Analysis Complete!")
                    
                    # Metrics
                    m1, m2 = st.columns(2)
                    m1.metric("🌐 Organic Rank", results.get("organic_rank") or "Not Found")
                    m2.metric("📍 Map Pack Rank", results.get("local_rank") or "Not Found")

                    # Results Details
                    st.divider()
                    st.subheader("📋 Search Results")
                    
                    col_local, col_organic = st.columns(2)

                    with col_local:
                        with st.expander("📍 Map Pack Results", expanded=True):
                            local_list = results.get("all_local", [])
                            if local_list:
                                for i, title in enumerate(local_list, 1):
                                    if brand.lower() in title.lower():
                                        st.markdown(f"**{i}. {title}** 🎯")
                                    else:
                                        st.text(f"{i}. {title}")
                            else:
                                st.info("No map pack results")

                    with col_organic:
                        with st.expander("🌐 Organic Results", expanded=True):
                            organic_list = results.get("all_organic", [])
                            if organic_list:
                                for i, link in enumerate(organic_list, 1):
                                    if domain.lower() in link.lower():
                                        st.markdown(f"**{i}. {link}** ✅")
                                    else:
                                        st.caption(f"{i}. {link}")
                            else:
                                st.info("No organic results")

                    # Save to database
                    save_result(results, city, area, lat, lng, brand, domain)
                    st.success("💾 Saved to history!")

            except requests.exceptions.Timeout:
                st.error("⏰ Request timed out (45s). Playwright takes time.")
            except Exception as e:
                st.error(f"❌ Connection Error: {e}")

# Historical Trends - FIXED CHART
if keyword and st.session_state.backend_ready:
    st.divider()
    st.subheader("📈 Ranking History")
    history, columns = get_keyword_history(final_keyword, city)
    if history:
        df = pd.DataFrame(history, columns=columns)
        chart_data = df.tail(10).copy()
        
        # Fixed chart with proper numeric conversion + deprecation fix
        numeric_df = pd.DataFrame()
        if 'organic_rank' in chart_data.columns:
            numeric_df['organic_rank'] = pd.to_numeric(chart_data['organic_rank'], errors='coerce').fillna(50)
        if 'local_rank' in chart_data.columns:
            numeric_df['local_rank'] = pd.to_numeric(chart_data['local_rank'], errors='coerce').fillna(50)
        
        if not numeric_df.empty and 'date_checked' in chart_data.columns:
            st.line_chart(numeric_df.set_index(chart_data['date_checked']))
        
        st.dataframe(df.tail(10), width="stretch")  # ✅ Fixed deprecation
    else:
        st.info("📝 No historical data yet. Check rankings to build history.")

st.sidebar.info("👈 Backend auto-starts & auto-closes!")
