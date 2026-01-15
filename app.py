import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# --- Configuração da Página ---
st.set_page_config(
    page_title="Mercado da Nícia", # NOME AJUSTADO
    page_icon="🛒", # ÍCONE AJUSTADO
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS Personalizado ---
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        font-weight: bold;
        height: 3em;
    }
    .suggestion-highlight {
        color: #e67e22;
        font-weight: bold;
        font-size: 14px;
    }
    .price-history {
        font-size: 12px;
        color: #2980b9;
        margin-bottom: -15px;
    }
    div[data-testid="stExpander"] {
        border: none;
        box-shadow: none;
    }
    </style>
""", unsafe_allow_html=True)

# --- CONEXÃO GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("MercadoApp_DB") 
        return sheet
    except Exception as e:
        return None

def load_data():
    sh = conectar_google_sheets()
    if not sh:
        st.error("🚨 Erro de conexão com Google Sheets.")
        return pd.DataFrame(), pd.DataFrame()

    try:
        ws_prod = sh.worksheet("produtos")
        data_prod = ws_prod.get_all_records()
        df_prod = pd.DataFrame(data_prod)

        ws_hist = sh.worksheet("historico")
        data_hist = ws_hist.get_all_records()
        df_hist = pd.DataFrame(data_hist)

        if not df_prod.empty:
            cols = ['ID', 'Preco', 'Estoque_Atual', 'Estoque_Minimo']
            for c in cols:
                if c in df_prod.columns:
                    df_prod[c] = pd.to_numeric(df_prod[c], errors='coerce').fillna(0)
            
            # Ordenação Alfabética
            df_prod = df_prod.sort_values(by='Produto', ascending=True)

        if not df_hist.empty:
            cols_h = ['Produto_ID', 'Qtd', 'Preco_Na_Epoca']
            for c in cols_h:
                if c in df_hist.columns:
                    df_hist[c] = pd.to_numeric(df_hist[c], errors='coerce').fillna(0)
                    
        return df_prod, df_hist
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

def save_data(df_prod, df_hist):
    sh = conectar_google_sheets()
    if sh:
        ws_prod = sh.worksheet("produtos")
        ws_prod.clear()
        ws_prod.update([df_prod.columns.values.tolist()] + df_prod.values.tolist())
        
        ws_hist = sh.worksheet("historico")
        ws_hist.clear()
        ws_hist.update([df_hist.columns.values.tolist()] + df_hist.values.tolist())

# --- CÁLCULO DE SUGESTÃO ---
def calcular_sugestao(row, df_hist):
    prod_id = row['ID']
    estoque_atual = row['Estoque_Atual']
    estoque_minimo = row['Estoque_Minimo']

    hist = df_hist[df_hist['Produto_ID'] == prod_id].sort_values(by='Data', ascending=False)
    levs = hist[hist['Tipo'] == 'LEVANTAMENTO']
    
    sugestao = 0
    motivo = ""
    
    if len(levs) >= 2:
        ultimo = levs.iloc[0]
        penultimo = levs.iloc[1]
        
        dt_atual = datetime.strptime(ultimo['Data'], "%Y-%m-%d %H:%M:%S")
        dt_anterior = datetime.strptime(penultimo['Data'], "%Y-%m-%d %H:%M:%S")
        
        dias = (dt_atual - dt_anterior).days
        if dias == 0: dias = 1
        
        mask_compras = (hist['Tipo'] == 'COMPRA') & \
                       (pd.to_datetime(hist['Data']) > dt_anterior) & \
                       (pd.to_datetime(hist['Data']) <= dt_atual)
        
        compras = hist.loc[mask_compras, 'Qtd'].sum()
        consumido = (penultimo['Qtd'] + compras) - ultimo['Qtd']
        if consumido < 0: consumido = 0
        
        consumo_mensal = (consumido / dias) * 30
        
        if consumo_mensal > estoque_atual:
            sugestao = consumo_mensal - estoque_atual
            motivo = f"Média consumo: {consumo_mensal:.1f}"
    else:
        if estoque_minimo > estoque_atual:
            sugestao = estoque_minimo - estoque_atual
            motivo = f"Abaixo do mínimo"

    return int(sugestao + 0.9), motivo

# --- APLICAÇÃO ---
st.title("🛒 Mercado da Nícia") # TÍTULO AJUSTADO
df_produtos, df_historico = load_data()

tab_carrinho, tab_estoque, tab_gerenciar = st.tabs([
    "🛒 Fazer Compras", "🏠 Estoque Casa", "⚙️ Gerenciar"
])

# =========================================================
# ABA 1: CARRINHO (Com lógica de Preço Histórico)
# =========================================================
with tab_carrinho:
    st.markdown("### Lista de Compras")
    st.caption("Preencha a quantidade e o preço atual dos itens que está comprando.")

    if df_produtos.empty:
        st.info("Cadastre produtos na aba 'Gerenciar'.")
    else:
        with st.form("form_compras"):
            inputs_qtd = {}
            inputs_preco = {}
            
            for idx, row in df_produtos.iterrows():
                sugestao, motivo = calcular_sugestao(row, df_historico)
                
                # Nome do Produto
                st.markdown(f"**{row['Produto']}**")
                
                if sugestao > 0:
                    st.markdown(f"<span class='suggestion-highlight'>💡 Levar: {sugestao} un ({motivo})</span>", unsafe_allow_html=True)
                
                c1, c2 = st.columns(2)
                
                # Campo Quantidade
                inputs_qtd[row['ID']] = c1.number_input(
                    "Qtd", 
                    min_value=0, 
                    step=1, 
                    key=f"qtd_{row['ID']}"
                )
                
                # Campo Preço (Puxa o histórico)
                ultimo_preco = float(row['Preco'])
                
                # Texto auxiliar para mostrar se aumentou ou diminuiu
                if ultimo_preco > 0:
                    c2.markdown(f"<p class='price-history'>Último: R$ {ultimo_preco:.2f}</p>", unsafe_allow_html=True)
                else:
                    c2.markdown(f"<p class='price-history'>Novo Produto</p>", unsafe_allow_html=True)

                inputs_preco[row['ID']] = c2.number_input(
                    "R$ Atual", 
                    min_value=0.0, 
                    value=ultimo_preco, # Vem preenchido com o último pago
                    step=0.01, 
                    key=f"prc_{row['ID']}"
                )
                st.divider()

            if st.form_submit_button("✅ FINALIZAR E SALVAR COMPRAS", type="primary"):
                compras_realizadas = []
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                for pid, qtd in inputs_qtd.items():
                    if qtd > 0: 
                        preco_novo = inputs_preco[pid]
                        
                        # Atualiza Estoque + ATUALIZA PREÇO PARA A PRÓXIMA VEZ
                        df_produtos.loc[df_produtos['ID'] == pid, 'Estoque_Atual'] += qtd
                        df_produtos.loc[df_produtos['ID'] == pid, 'Preco'] = preco_novo
                        
                        compras_realizadas.append({
                            'Data': now, 
                            'Produto_ID': pid,
                            'Tipo': 'COMPRA', 
                            'Qtd': qtd, 
                            'Preco_Na_Epoca': preco_novo
                        })
                
                if compras_realizadas:
                    df_historico = pd.concat([df_historico, pd.DataFrame(compras_realizadas)], ignore_index=True)
                    save_data(df_produtos, df_historico)
                    st.balloons()
                    st.success(f"{len(compras_realizadas)} produtos registrados! Preços atualizados.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.warning("Preencha a quantidade de pelo menos 1 item.")

# =========================================================
# ABA 2: ESTOQUE CASA
# =========================================================
with tab_estoque:
    st.markdown("### Auditoria de Estoque")
    st.caption("Quanto você tem em casa hoje?")

    if df_produtos.empty:
        st.info("Sem produtos.")
    else:
        with st.form("form_estoque"):
            inputs_estoque = {}
            
            for idx, row in df_produtos.iterrows():
                c1, c2 = st.columns([2, 1])
                c1.markdown(f"**{row['Produto']}**")
                c1.caption(f"Sistema: {int(row['Estoque_Atual'])}")
                
                inputs_estoque[row['ID']] = c2.number_input(
                    "Real", 
                    min_value=0, 
                    step=1, 
                    value=int(row['Estoque_Atual']),
                    key=f"est_{row['ID']}",
                    label_visibility="collapsed"
                )
                st.markdown("---")

            if st.form_submit_button("💾 SALVAR CONTAGEM"):
                alteracoes = False
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logs_audit = []

                for pid, novo_valor in inputs_estoque.items():
                    valor_antigo = int(df_produtos.loc[df_produtos['ID'] == pid, 'Estoque_Atual'].values[0])
                    
                    if novo_valor != valor_antigo:
                        alteracoes = True
                        df_produtos.loc[df_produtos['ID'] == pid, 'Estoque_Atual'] = novo_valor
                        
                        logs_audit.append({
                            'Data': now,
                            'Produto_ID': pid, 
                            'Tipo': 'LEVANTAMENTO',
                            'Qtd': novo_valor, 
                            'Preco_Na_Epoca': 0
                        })
                
                if alteracoes:
                    df_historico = pd.concat([df_historico, pd.DataFrame(logs_audit)], ignore_index=True)
                    save_data(df_produtos, df_historico)
                    st.success("Estoque atualizado!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.info("Nenhuma alteração.")

# =========================================================
# ABA 3: GERENCIAR (SEM PREÇO)
# =========================================================
with tab_gerenciar:
    st.markdown("### ⚙️ Cadastro de Produtos")
    
    with st.expander("➕ Novo Produto", expanded=True):
        with st.form("cad_form", clear_on_submit=True):
            nome = st.text_input("Nome do Produto")
            marca = st.text_input("Marca")
            
            c1, c2 = st.columns(2)
            # Preço foi removido daqui conforme solicitado
            est_inicial = c1.number_input("Estoque Inicial (Casa)", min_value=0, value=0)
            minimo = c2.number_input("Estoque Mínimo", min_value=1, value=1)
            
            if st.form_submit_button("Cadastrar"):
                if nome:
                    nid = len(df_produtos) + 1
                    if not df_produtos.empty and nid in df_produtos['ID'].values:
                        nid = df_produtos['ID'].max() + 1
                        
                    novo = {
                        'ID': nid, 
                        'Produto': nome, 
                        'Marca': marca,
                        'Preco': 0.0, # Começa com zero. Será atualizado na primeira compra.
                        'Estoque_Atual': est_inicial, 
                        'Estoque_Minimo': minimo
                    }
                    df_produtos = pd.concat([df_produtos, pd.DataFrame([novo])], ignore_index=True)
                    
                    log = {
                        'Data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'Produto_ID': nid, 'Tipo': 'LEVANTAMENTO',
                        'Qtd': est_inicial, 'Preco_Na_Epoca': 0
                    }
                    df_historico = pd.concat([df_historico, pd.DataFrame([log])], ignore_index=True)
                    
                    save_data(df_produtos, df_historico)
                    st.success(f"{nome} cadastrado!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Nome é obrigatório.")

    st.write("---")
    with st.expander("🗑️ Excluir Produto"):
        if not df_produtos.empty:
            lista_prods = df_produtos['Produto'].tolist()
            p_del = st.selectbox("Selecione para excluir:", lista_prods)
            
            if st.button("Confirmar Exclusão"):
                df_produtos = df_produtos[df_produtos['Produto'] != p_del]
                save_data(df_produtos, df_historico)
                st.error("Produto excluído!")
                time.sleep(1)
                st.rerun()
                
