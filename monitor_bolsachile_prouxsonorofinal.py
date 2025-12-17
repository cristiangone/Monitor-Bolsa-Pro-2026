import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
import time
import base64
from datetime import datetime, time as dt_time
import pytz
import plotly.graph_objects as go

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
st.set_page_config(page_title="Monitor Pro | Bolsa Santiago", page_icon="📈", layout="wide")
ZONA_HORARIA = pytz.timezone('America/Santiago')

# Inicializar conexión con Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

# Inicializar estado para control de alertas
if 'alertas_disparadas' not in st.session_state:
    st.session_state['alertas_disparadas'] = set()

# --- 2. ESTILOS GLOBALES UNIFICADOS (CSS) ---
st.markdown("""
    <style>
    /* === TIPOGRAFÍA Y COLORES GLOBALES === */
    .stApp { 
        background-color: #0d1117; 
        font-family: 'Inter', sans-serif; 
    }
    
    h1, h2, h3, h4, h5, h6, .stMarkdown, p { color: #FFFFFF !important; }

    /* === BARRA LATERAL === */
    [data-testid="stSidebar"] { background-color: #1E1E1E !important; border-right: 1px solid #333; }
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] p { color: #E0E0E0 !important; }
    .stTextInput > div > div > input { color: #FFFFFF; background-color: #2D2D2D; }

    /* === TARJETAS === */
    [data-testid="stMetricLabel"] {
        color: #F0F2F6 !important; font-size: 16px !important; font-weight: 600 !important;
        text-transform: uppercase; letter-spacing: 1px;
    }
    [data-testid="stMetricValue"] { 
        color: #FFFFFF !important; font-size: 28px !important; font-weight: 700; letter-spacing: -0.5px;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #161b22; border-radius: 12px; border: 1px solid #30363d;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #58a6ff; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }

    /* === MODO KIOSCO === */
    [data-testid="stToolbar"] { visibility: hidden; height: 0px; }
    header { visibility: hidden; height: 0px; }
    footer { visibility: hidden; height: 0px; }
    .block-container { padding-top: 2rem !important; padding-bottom: 1rem !important; }

    /* === COMPONENTES EXTRA === */
    .status-badge { padding: 4px 8px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; }
    .status-open { background-color: rgba(46, 160, 67, 0.15); color: #3fb950; border: 1px solid #2ea043; }
    .status-closed { background-color: rgba(218, 54, 51, 0.15); color: #f85149; border: 1px solid #da3633; }
    
    @media only screen and (max-width: 600px) {
        [data-testid="stMetricValue"] { font-size: 24px !important; }
        .stPlotlyChart { height: 150px !important; }
    }
    </style>
""", unsafe_allow_html=True)


# --- 3. FUNCIONES LÓGICAS ---

def esta_mercado_abierto():
    ahora = datetime.now(ZONA_HORARIA).time()
    # Ajusta aquí los horarios si es necesario
    return dt_time(9, 0) <= ahora <= dt_time(17, 0)

def reproducir_audio(tipo):
    archivo = "success.mp3" if tipo == "up" else "warning.mp3"
    # Nota: En Streamlit Cloud el audio local puede ser tricky si no subes los mp3.
    # Idealmente usa URLs públicas o asegura que los mp3 estén en el repo.
    try:
        with open(archivo, "rb") as f:
            data = f.read()
            b64 = base64.b64encode(data).decode()
            md = f"""
                <audio autoplay style="display:none;">
                <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
                </audio>
            """
            st.markdown(md, unsafe_allow_html=True)
    except:
        pass

def gestionar_alertas(nemo, variacion, activar_sonido):
    umbral = 2.0
    direccion = "UP" if variacion > 0 else "DOWN"
    alert_id = f"{nemo}_{direccion}"
    
    if abs(variacion) >= umbral:
        if alert_id not in st.session_state['alertas_disparadas']:
            icono = "🚀" if variacion > 0 else "🔻"
            st.toast(f"{icono} ALERTA: {nemo} movió un {variacion:.2f}%", icon="🔔")
            if activar_sonido:
                reproducir_audio("up" if variacion > 0 else "down")
            st.session_state['alertas_disparadas'].add(alert_id)
    else:
        ids_a_borrar = [x for x in st.session_state['alertas_disparadas'] if x.startswith(nemo)]
        for x in ids_a_borrar:
            st.session_state['alertas_disparadas'].discard(x)

# --- NUEVAS FUNCIONES DE GOOGLE SHEETS OPTIMIZADAS ---

# Definimos el nombre en una constante para no equivocarnos
NOMBRE_HOJA = "Hoja1" 

def cargar_historial():
    """Lee datos desde Google Sheets con manejo de errores robusto"""
    try:
        # ttl=0 evita que Streamlit use caché vieja
        df = conn.read(worksheet=NOMBRE_HOJA, ttl=0)
        
        # Si la hoja existe pero está vacía o sin columnas correctas
        if df.empty or 'NEMO' not in df.columns:
            return pd.DataFrame(columns=['Fecha', 'NEMO', 'Precio', 'Var'])
            
        # Limpieza y conversión de tipos
        df['Fecha'] = pd.to_datetime(df['Fecha'])
        df['Precio'] = pd.to_numeric(df['Precio'], errors='coerce')
        df['Var'] = pd.to_numeric(df['Var'], errors='coerce')
        
        return df.sort_values('Fecha')
        
    except Exception as e:
        # Si falla (ej: la hoja no se llama 'Hoja1'), devolvemos un DF vacío para no romper la app
        # Opcional: imprimir el error en consola para ti
        print(f"DEBUG - Error cargando historial: {e}") 
        return pd.DataFrame(columns=['Fecha', 'NEMO', 'Precio', 'Var'])

def guardar_datos(nuevos_datos):
    """Guarda nuevos datos concatenando y reescribiendo"""
    if not nuevos_datos: return

    timestamp = datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')
    registros = []
    
    # Procesar datos de la API
    for item in nuevos_datos:
        if item.get('NEMO'):
            registros.append({
                'Fecha': timestamp,
                'NEMO': item.get('NEMO'),
                'Precio': item.get('PRE_ULT_TR', 0),
                'Var': item.get('VAR_PRE', 0) 
            })
    
    if not registros: return

    df_nuevos = pd.DataFrame(registros)
    df_actual = cargar_historial()
    
    # Concatenar asegurando que los índices se ignoren
    df_final = pd.concat([df_actual, df_nuevos], ignore_index=True)
    
    # Escribir de vuelta a Sheets
    try:
        conn.update(worksheet=NOMBRE_HOJA, data=df_final)
        # Feedback visual sutil (Opcional, si molesta quítalo)
        # st.toast("Datos sincronizados con Sheets", icon="☁️")
    except Exception as e:
        st.error(f"⚠️ Error crítico guardando en Sheets: Verifica que la hoja se llame '{NOMBRE_HOJA}' y que el bot tenga permisos de Editor.")
        print(f"DEBUG - Error guardando: {e}")
        
def obtener_datos_api(url, key):
    try:
        r = requests.get(f"{url}/Instrumentos", headers={"Ocp-Apim-Subscription-Key": key}, timeout=10)
        return (r.json(), "OK") if r.status_code == 200 else (None, f"Error {r.status_code}")
    except Exception as e: return None, str(e)

# --- 4. INTERFAZ ---

with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = st.text_input("API Key:", value=st.secrets.get("BRAINDATA_KEY", ""), type="password")
    url_base = st.text_input("URL Base:", value="https://api-private-braindata.bolsadesantiago.com/api-servicios-de-consulta/api/Util")
    
    st.divider()
    
    st.subheader("🔔 Alertas")
    activar_sonido = st.toggle("Activar Sonido", value=True)
    st.caption("Suena si la variación > 2% o < -2%")
    
    st.divider()
    
    modo_auto = st.checkbox("🔄 Auto-Actualizar", value=True)
    # Aumenté el mínimo a 10 min para no saturar Google Sheets y evitar bloqueos de API
    frecuencia = st.number_input("Minutos:", min_value=1, value=10)
    
    if st.button("🗑️ Limpiar Historial Nube"):
        # Borra todo y deja solo los encabezados
        df_vacio = pd.DataFrame(columns=['Fecha', 'NEMO', 'Precio', 'Var'])
        conn.update(worksheet="Hoja 1", data=df_vacio)
        st.session_state['alertas_disparadas'] = set()
        st.rerun()

st.title("🇨🇱 Monitor Bolsa de Santiago")
hora = datetime.now(ZONA_HORARIA).strftime('%H:%M:%S')

# Indicador de Estado
estado_clase = "status-open" if esta_mercado_abierto() else "status-closed"
estado_texto = "MERCADO ABIERTO" if esta_mercado_abierto() else "MERCADO CERRADO"
st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
        <span class='status-badge {estado_clase}'>● {estado_texto}</span>
        <span style='color: #8b949e; font-size: 0.9rem;'>Actualizado: {hora}</span>
    </div>
""", unsafe_allow_html=True)

if not api_key:
    st.warning("⚠️ Ingresa tu API Key en la barra lateral.")
else:
    # 1. Obtener datos
    data_raw, msg = obtener_datos_api(url_base, api_key)
    
    if msg == "OK":
        # 2. Guardar en Nube (Google Sheets)
        guardar_datos(data_raw)
        
        # 3. Leer historial completo desde la Nube
        df_hist = cargar_historial()
        
        acciones = [x for x in data_raw if x.get('NEMO')]
        columnas = st.columns(3)
        
        for i, accion in enumerate(acciones):
            nemo = accion.get('NEMO')
            precio = accion.get('PRE_ULT_TR', 0)
            
            with columnas[i % 3]:
                with st.container(border=True):
                    
                    # Preparar Datos para esta acción específica
                    df_nemo = pd.DataFrame()
                    delta = 0
                    color_chart = "#2ea043" # Verde
                    color_fill = "rgba(46, 160, 67, 0.1)"
                    
                    if not df_hist.empty and 'NEMO' in df_hist.columns:
                        df_nemo = df_hist[df_hist['NEMO'] == nemo]
                    
                    if not df_nemo.empty and len(df_nemo) > 0:
                        try:
                            primero = df_nemo.iloc[0]['Precio']
                            ultimo = df_nemo.iloc[-1]['Precio']
                            if primero > 0:
                                delta = ((ultimo - primero) / primero) * 100
                            
                            if ultimo < primero:
                                color_chart = "#da3633" # Rojo
                                color_fill = "rgba(218, 54, 51, 0.1)"
                        except: pass
                    
                    # LÓGICA DE ALERTA
                    gestionar_alertas(nemo, delta, activar_sonido)

                    # UI Tarjeta
                    st.caption(f"{nemo}")
                    st.metric("Precio Actual", f"${precio:,.2f}", f"{delta:.2f}%")
                    
                    # Gráfico Sparkline
                    if not df_nemo.empty and len(df_nemo) > 1:
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=df_nemo['Fecha'], 
                            y=df_nemo['Precio'],
                            mode='lines',
                            fill='tozeroy',
                            line=dict(color=color_chart, width=2),
                            fillcolor=color_fill,
                            hovertemplate='%{y:$.2f}<extra></extra>'
                        ))
                        # Ajustar escala Y dinámicamente
                        min_y = df_nemo['Precio'].min() * 0.999
                        max_y = df_nemo['Precio'].max() * 1.001
                        
                        fig.update_layout(
                            height=120, 
                            margin=dict(l=0, r=0, t=5, b=0),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            showlegend=False,
                            xaxis=dict(visible=False), 
                            yaxis=dict(visible=False, range=[min_y, max_y]),
                            hovermode="x unified"
                        )
                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'staticPlot': False})
                    else:
                        st.markdown("<div style='height: 120px; display: flex; align-items: center; justify-content: center; color: #8b949e; font-size: 0.8rem;'>Esperando más datos históricos...</div>", unsafe_allow_html=True)
    else:
        st.error(f"Error de conexión: {msg}")

    # Refresco Automático
    if modo_auto:
        # Nota: Google Sheets tiene límites de escritura (aprox 60 por minuto por usuario).
        # Ten cuidado de no bajar mucho este tiempo si tienes muchos usuarios.
        time.sleep(frecuencia * 60)
        st.rerun()

