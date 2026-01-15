import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# --- Configuração da Página (Visual Mobile) ---
st.set_page_config(
    page_title="Mercado Fácil",
    page_icon="🛒",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- Estilização CSS Personalizada (Para dar cor e ajustar mobile) ---
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        font-weight: bold;
    }
    div[data-testid="stMetricValue"] {
        font-size: 24px;
    }
    </style>
""", unsafe_allow_html=True)

# --- CONEXÃO COM GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    # Tenta conectar usando segredos do Streamlit
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # Reconstrói o dicionário de credenciais a partir dos segredos
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Abre a planilha (Certifique-se que o nome no Google Sheets é EXATAMENTE este)
        sheet = client.open("MercadoApp_DB") 
        return sheet
    except Exception as e:
        return None

def load_data():
    sh = conectar_google_sheets()
    if not sh:
        st.error("🚨 Erro de conexão! Verifique se configurou os 'Secrets' no Streamlit.")
        return pd.DataFrame(), pd.DataFrame()

    try:
        # Carrega Produtos
        ws_prod = sh.worksheet("produtos")
        data_prod = ws_prod.get_all_records()
        df_prod = pd.DataFrame(data_prod)

        # Carrega Histórico
        ws_hist = sh.worksheet("historico")
        data_hist = ws_hist.get_all_records()
        df_hist = pd.DataFrame(data_hist)

        # Converte colunas numéricas (segurança contra texto do Sheets)
        if not df_prod.empty:
            cols = ['ID', 'Preco', 'Estoque_Atual', 'Estoque_Minimo']
            for c in cols:
                if c in df_prod.columns:
                    df_prod[c] = pd.to_numeric(df_prod[c], errors='coerce').fillna(0)

        if not df_hist.empty:
            cols_h = ['Produto_ID', 'Qtd', 'Preco_Na_Epoca']
            for c in cols_h:
                if c in df_hist.columns:
                    df_hist[c] = pd.to_numeric(df_hist[c], errors='coerce').fillna(0)
                    
        return df_prod, df_hist
    except Exception as e:
        st.error(f"Erro ao ler abas: {e}")
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

# --- LÓGICA DE CONSUMO (MÉDIA 30 DIAS) ---
def calcular_consumo(prod_id, df_hist):
    # Filtra histórico do produto
    hist = df_hist[df_hist['Produto_ID'] == prod_id].sort_values(by='Data', ascending=False)
    
    # Pega apenas auditorias (Levantamentos)
    levs = hist[hist['Tipo'] == 'LEVANTAMENTO']
    
    if len(levs) < 2: return None # Precisa de 2 pontos para traçar média
    
    ultimo = levs.iloc[0]
    penultimo = levs.iloc[1]
    
    dt_atual = datetime.strptime(ultimo['Data'], "%Y-%m-%d %H:%M:%S")
    dt_anterior = datetime.strptime(penultimo['Data'], "%Y-%m-%d %H:%M:%S")
    
    dias = (dt_atual - dt_anterior).days
    if dias == 0: dias = 1
    
    # Soma compras no intervalo
    mask_compras = (hist['Tipo'] == 'COMPRA') & \
                   (pd.to_datetime(hist['Data']) > dt_anterior) & \
                   (pd.to_datetime(hist['Data']) <= dt_atual)
    
    compras = hist.loc[mask_compras, 'Qtd'].sum()
    
    # Estoque Anterior + Entradas - Estoque Atual = Saída (Consumo)
    consumido = (penultimo['Qtd'] + compras) - ultimo['Qtd']
    if consumido < 0: consumido = 0
    
    # Projeção mensal
    media = (consumido / dias) * 30
    return round(media, 1)

# --- INÍCIO DA APP ---
st.title("🍓 Mercado Fácil")
df_produtos, df_historico = load_data()

# Inicializa Carrinho
if 'carrinho' not in st.session_state:
    st.session_state.carrinho = []

# --- MENU DE NAVEGAÇÃO ---
tab_sugestao, tab_carrinho, tab_estoque, tab_novo = st.tabs([
    "📋 Lista", "🛒 Carrinho", "🏠 Casa", "➕ Novo"
])

# =========================================================
# ABA 1: LISTA MÁGICA (Sugestões)
# =========================================================
with tab_sugestao:
    st.markdown("### 💡 O que falta comprar?")
    
    if df_produtos.empty:
        st.info("Cadastre produtos na aba 'Novo' para começar!")
    else:
        lista_final = []
        total_previsto = 0
        
        for idx, row in df_produtos.iterrows():
            consumo = calcular_consumo(row['ID'], df_historico)
            
            sugestao = 0
            motivo = ""
            cor_motivo = "blue"
            
            if consumo is not None:
                necessidade = consumo - row['Estoque_Atual']
                if necessidade > 0:
                    sugestao = necessidade
                    motivo = f"Consumo: {consumo}/mês"
            else:
                necessidade = row['Estoque_Minimo'] - row['Estoque_Atual']
                if necessidade > 0:
                    sugestao = necessidade
                    motivo = "Estoque Baixo"
                    cor_motivo = "orange"
            
            sugestao = int(sugestao + 0.9) # Arredonda pra cima
            
            if sugestao > 0:
                custo = sugestao * row['Preco']
                total_previsto += custo
                lista_final.append({
                    "Produto": row['Produto'],
                    "Falta": f"{sugestao}",
                    "Custo": f"R$ {custo:.2f}",
                    "_motivo": motivo
                })
        
        if lista_final:
            st.info(f"💰 Previsão de Gasto: **R$ {total_previsto:.2f}**")
            
            # Exibição Customizada (Melhor que tabela padrão no celular)
            for item in lista_final:
                with st.container():
                    c1, c2, c3 = st.columns([3, 1, 2])
                    c1.markdown(f"**{item['Produto']}**")
                    c1.caption(f"{item['_motivo']}")
                    c2.markdown(f"📦 **{item['Falta']}**")
                    c3.markdown(f":green[{item['Custo']}]")
                    st.divider()
        else:
            st.balloons()
            st.success("Tudo cheio! Nada para comprar hoje.")

# =========================================================
# ABA 2: CAIXA (Carrinho)
# =========================================================
with tab_carrinho:
    st.markdown("### 🛒 Hora das Compras")
    
    with st.expander("🔎 Buscar Produto", expanded=True):
        if not df_produtos.empty:
            sel_prod = st.selectbox("Escolha o item:", df_produtos['Produto'].unique())
            dados = df_produtos[df_produtos['Produto'] == sel_prod].iloc[0]
            
            c1, c2 = st.columns(2)
            q_compra = c1.number_input("Qtd", min_value=1, step=1, key="q_c")
            p_compra = c2.number_input("Preço R$", value=float(dados['Preco']), step=0.10, key="p_c")
            
            if st.button("⬇️ Colocar no Carrinho", type="primary"):
                st.session_state.carrinho.append({
                    'ID': dados['ID'], 'Produto': sel_prod,
                    'Qtd': q_compra, 'Preco': p_compra,
                    'Total': q_compra * p_compra
                })
                st.toast(f"{sel_prod} adicionado!", icon='🛒')

    if st.session_state.carrinho:
        st.write("---")
        df_c = pd.DataFrame(st.session_state.carrinho)
        
        # Mostra Carrinho
        st.dataframe(
            df_c[['Produto', 'Qtd', 'Total']],
            use_container_width=True,
            hide_index=True,
            column_config={"Total": st.column_config.NumberColumn(format="R$ %.2f")}
        )
        
        total_carrinho = df_c['Total'].sum()
        st.markdown(f"<h2 style='text-align: center; color: green;'>Total: R$ {total_carrinho:.2f}</h2>", unsafe_allow_html=True)
        
        col_ok, col_del = st.columns(2)
        if col_ok.button("✅ Finalizar"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logs = []
            
            with st.spinner("Salvando na nuvem..."):
                for item in st.session_state.carrinho:
                    # Atualiza RAM
                    df_produtos.loc[df_produtos['ID'] == item['ID'], 'Estoque_Atual'] += item['Qtd']
                    df_produtos.loc[df_produtos['ID'] == item['ID'], 'Preco'] = item['Preco']
                    # Prepara Log
                    logs.append({
                        'Data': now, 'Produto_ID': item['ID'],
                        'Tipo': 'COMPRA', 'Qtd': item['Qtd'], 'Preco_Na_Epoca': item['Preco']
                    })
                
                # Salva
                df_historico = pd.concat([df_historico, pd.DataFrame(logs)], ignore_index=True)
                save_data(df_produtos, df_historico)
                
                st.session_state.carrinho = []
                st.success("Compra registrada!")
                time.sleep(1)
                st.rerun()

        if col_del.button("🗑️ Limpar"):
            st.session_state.carrinho = []
            st.rerun()

# =========================================================
# ABA 3: ESTOQUE (Casa)
# =========================================================
with tab_estoque:
    st.markdown("### 🏠 Contagem em Casa")
    
    if not df_produtos.empty:
        p_inv = st.selectbox("Qual produto você vai contar?", df_produtos['Produto'].unique(), key="s_inv")
        row_inv = df_produtos[df_produtos['Produto'] == p_inv].iloc[0]
        
        # Cards visuais
        c1, c2 = st.columns(2)
        c1.metric("Sistema diz:", f"{int(row_inv['Estoque_Atual'])}")
        c2.metric("Mínimo ideal:", f"{int(row_inv['Estoque_Minimo'])}")
        
        st.write("---")
        novo_val = st.number_input(f"Quantos {p_inv} tem REALMENTE aí?", min_value=0, step=1)
        
        if st.button("💾 Atualizar Estoque"):
            with st.spinner("Atualizando..."):
                # Atualiza RAM
                df_produtos.loc[df_produtos['ID'] == row_inv['ID'], 'Estoque_Atual'] = novo_val
                
                # Log
                log = {
                    'Data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'Produto_ID': row_inv['ID'], 'Tipo': 'LEVANTAMENTO',
                    'Qtd': novo_val, 'Preco_Na_Epoca': 0
                }
                df_historico = pd.concat([df_historico, pd.DataFrame([log])], ignore_index=True)
                
                save_data(df_produtos, df_historico)
                st.success(f"Estoque de {p_inv} corrigido para {novo_val}!")
                time.sleep(1)
                st.rerun()

# =========================================================
# ABA 4: NOVO CADASTRO
# =========================================================
with tab_novo:
    st.markdown("### ➕ Cadastrar Produto")
    
    with st.form("cad_form"):
        nome = st.text_input("Nome do Produto (ex: Arroz 5kg)")
        marca = st.text_input("Marca (Opcional)")
        c1, c2 = st.columns(2)
        preco = c1.number_input("Preço Médio", min_value=0.01)
        minimo = c2.number_input("Estoque Mínimo", min_value=1, value=1)
        
        if st.form_submit_button("Salvar Produto"):
            if nome:
                with st.spinner("Cadastrando..."):
                    nid = len(df_produtos) + 1
                    novo = {
                        'ID': nid, 'Produto': nome, 'Marca': marca,
                        'Preco': preco, 'Estoque_Atual': 0, 'Estoque_Minimo': minimo
                    }
                    df_produtos = pd.concat([df_produtos, pd.DataFrame([novo])], ignore_index=True)
                    
                    # Log inicial
                    log = {
                        'Data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'Produto_ID': nid, 'Tipo': 'LEVANTAMENTO',
                        'Qtd': 0, 'Preco_Na_Epoca': 0
                    }
                    df_historico = pd.concat([df_historico, pd.DataFrame([log])], ignore_index=True)
                    
                    save_data(df_produtos, df_historico)
                    st.success(f"{nome} cadastrado com sucesso!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.warning("Escreva o nome do produto!")
