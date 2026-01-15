import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# --- Configuração da Página ---
st.set_page_config(
    page_title="Mercado Fácil",
    page_icon="🛒",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS para melhorar botões ---
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

        # Conversão de tipos
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
        # Se der erro (ex: planilha vazia), retorna vazio
        return pd.DataFrame(), pd.DataFrame()

def save_data(df_prod, df_hist):
    sh = conectar_google_sheets()
    if sh:
        # Atualiza Produtos
        ws_prod = sh.worksheet("produtos")
        ws_prod.clear()
        ws_prod.update([df_prod.columns.values.tolist()] + df_prod.values.tolist())
        
        # Atualiza Histórico
        ws_hist = sh.worksheet("historico")
        ws_hist.clear()
        ws_hist.update([df_hist.columns.values.tolist()] + df_hist.values.tolist())

# --- CÁLCULO DE CONSUMO ---
def calcular_consumo(prod_id, df_hist):
    hist = df_hist[df_hist['Produto_ID'] == prod_id].sort_values(by='Data', ascending=False)
    levs = hist[hist['Tipo'] == 'LEVANTAMENTO']
    
    if len(levs) < 2: return None
    
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
    
    media = (consumido / dias) * 30
    return round(media, 1)

# --- APP ---
st.title("🍓 Mercado Fácil")
df_produtos, df_historico = load_data()

if 'carrinho' not in st.session_state:
    st.session_state.carrinho = []

# Abas atualizadas
tab_sugestao, tab_carrinho, tab_estoque, tab_gerenciar = st.tabs([
    "📋 Lista", "🛒 Carrinho", "🏠 Casa", "⚙️ Gerenciar"
])

# =========================================================
# ABA 1: LISTA (Sugestões)
# =========================================================
with tab_sugestao:
    st.markdown("### 💡 Sugestão de Compra")
    
    if df_produtos.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        lista_final = []
        total_previsto = 0
        
        for idx, row in df_produtos.iterrows():
            consumo = calcular_consumo(row['ID'], df_historico)
            
            sugestao = 0
            motivo = ""
            
            # Lógica: Se tem histórico, usa média. Se não, usa mínimo.
            if consumo is not None:
                necessidade = consumo - row['Estoque_Atual']
                if necessidade > 0:
                    sugestao = necessidade
                    motivo = f"Consumo: {consumo}/mês"
            else:
                necessidade = row['Estoque_Minimo'] - row['Estoque_Atual']
                if necessidade > 0:
                    sugestao = necessidade
                    motivo = "Repor Mínimo"
            
            sugestao = int(sugestao + 0.9)
            
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
            st.info(f"💰 Previsão: **R$ {total_previsto:.2f}**")
            for item in lista_final:
                with st.container():
                    c1, c2, c3 = st.columns([3, 1, 2])
                    c1.markdown(f"**{item['Produto']}**")
                    c1.caption(f"{item['_motivo']}")
                    c2.markdown(f"📦{item['Falta']}")
                    c3.markdown(f":green[{item['Custo']}]")
                    st.divider()
        else:
            st.success("🎉 Estoque em dia!")

# =========================================================
# ABA 2: CARRINHO (Com Exclusão de Itens)
# =========================================================
with tab_carrinho:
    st.markdown("### 🛒 No Supermercado")
    
    # Adicionar item
    with st.expander("🔎 Buscar Produto", expanded=True):
        if not df_produtos.empty:
            sel_prod = st.selectbox("Item:", df_produtos['Produto'].unique())
            dados = df_produtos[df_produtos['Produto'] == sel_prod].iloc[0]
            
            c1, c2 = st.columns(2)
            q_compra = c1.number_input("Qtd", min_value=1, step=1, key="q_c")
            p_compra = c2.number_input("R$ Unit.", value=float(dados['Preco']), step=0.10, key="p_c")
            
            if st.button("⬇️ Adicionar", type="primary"):
                st.session_state.carrinho.append({
                    'ID': dados['ID'], 'Produto': sel_prod,
                    'Qtd': q_compra, 'Preco': p_compra,
                    'Total': q_compra * p_compra
                })
                st.rerun()

    # Visualizar e Gerenciar Carrinho
    if st.session_state.carrinho:
        st.write("---")
        df_c = pd.DataFrame(st.session_state.carrinho)
        
        st.dataframe(
            df_c[['Produto', 'Qtd', 'Total']],
            use_container_width=True,
            hide_index=True,
            column_config={"Total": st.column_config.NumberColumn(format="R$ %.2f")}
        )
        
        total_carrinho = df_c['Total'].sum()
        st.markdown(f"<h3 style='text-align:right; color:green'>Total: R$ {total_carrinho:.2f}</h3>", unsafe_allow_html=True)
        
        # Remover item específico
        itens_nomes = [f"{i['Produto']} ({i['Qtd']}un)" for i in st.session_state.carrinho]
        item_rem = st.multiselect("Remover item do carrinho:", options=itens_nomes)
        
        if item_rem:
            if st.button("🗑️ Remover Selecionados"):
                # Filtra o carrinho mantendo apenas o que NÃO foi selecionado
                # (Lógica simples baseada em nome/qtd para identificar)
                novo_carrinho = []
                for item in st.session_state.carrinho:
                    nome_formatado = f"{item['Produto']} ({item['Qtd']}un)"
                    if nome_formatado not in item_rem:
                        novo_carrinho.append(item)
                st.session_state.carrinho = novo_carrinho
                st.rerun()

        st.divider()
        if st.button("✅ FINALIZAR COMPRA", type="primary"):
            with st.spinner("Atualizando estoque..."):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logs = []
                
                for item in st.session_state.carrinho:
                    # Atualiza Estoque na memória
                    df_produtos.loc[df_produtos['ID'] == item['ID'], 'Estoque_Atual'] += item['Qtd']
                    df_produtos.loc[df_produtos['ID'] == item['ID'], 'Preco'] = item['Preco']
                    # Log
                    logs.append({
                        'Data': now, 'Produto_ID': item['ID'],
                        'Tipo': 'COMPRA', 'Qtd': item['Qtd'], 'Preco_Na_Epoca': item['Preco']
                    })
                
                # Salva no Google Sheets
                df_historico = pd.concat([df_historico, pd.DataFrame(logs)], ignore_index=True)
                save_data(df_produtos, df_historico)
                
                st.session_state.carrinho = []
                st.balloons()
                st.success("Compra salva!")
                time.sleep(1)
                st.rerun()
    else:
        st.info("Carrinho vazio.")

# =========================================================
# ABA 3: CASA (Atualizar Estoque)
# =========================================================
with tab_estoque:
    st.markdown("### 🏠 Auditoria de Estoque")
    
    if not df_produtos.empty:
        p_inv = st.selectbox("Produto:", df_produtos['Produto'].unique(), key="s_inv")
        row_inv = df_produtos[df_produtos['Produto'] == p_inv].iloc[0]
        
        c1, c2 = st.columns(2)
        c1.metric("Sistema:", f"{int(row_inv['Estoque_Atual'])}")
        c2.metric("Mínimo:", f"{int(row_inv['Estoque_Minimo'])}")
        
        novo_val = st.number_input("Quantidade Real (Contagem):", min_value=0, step=1)
        
        if st.button("💾 Corrigir Estoque"):
            with st.spinner("Salvando..."):
                df_produtos.loc[df_produtos['ID'] == row_inv['ID'], 'Estoque_Atual'] = novo_val
                
                log = {
                    'Data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'Produto_ID': row_inv['ID'], 'Tipo': 'LEVANTAMENTO',
                    'Qtd': novo_val, 'Preco_Na_Epoca': 0
                }
                df_historico = pd.concat([df_historico, pd.DataFrame([log])], ignore_index=True)
                
                save_data(df_produtos, df_historico)
                st.success("Atualizado!")
                time.sleep(1)
                st.rerun()

# =========================================================
# ABA 4: GERENCIAR (Novo + Excluir)
# =========================================================
with tab_gerenciar:
    st.markdown("### ⚙️ Gestão de Produtos")
    
    # --- CADASTRO ---
    with st.expander("➕ Cadastrar Novo Produto", expanded=True):
        with st.form("cad_form"):
            nome = st.text_input("Nome")
            marca = st.text_input("Marca")
            c1, c2 = st.columns(2)
            preco = c1.number_input("Preço Médio", min_value=0.01)
            minimo = c2.number_input("Estoque Mínimo", min_value=1, value=1)
            
            # Campo NOVO: Estoque Inicial
            est_inicial = st.number_input("Estoque Inicial (já tenho em casa):", min_value=0, value=0)
            
            if st.form_submit_button("Salvar Produto"):
                if nome:
                    nid = len(df_produtos) + 1
                    # Se ID já existe (caso tenha deletado algums), busca o próximo livre
                    if not df_produtos.empty and nid in df_produtos['ID'].values:
                        nid = df_produtos['ID'].max() + 1
                        
                    novo = {
                        'ID': nid, 'Produto': nome, 'Marca': marca,
                        'Preco': preco, 'Estoque_Atual': est_inicial, 'Estoque_Minimo': minimo
                    }
                    df_produtos = pd.concat([df_produtos, pd.DataFrame([novo])], ignore_index=True)
                    
                    # Log inicial
                    log = {
                        'Data': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'Produto_ID': nid, 'Tipo': 'LEVANTAMENTO',
                        'Qtd': est_inicial, 'Preco_Na_Epoca': 0
                    }
                    df_historico = pd.concat([df_historico, pd.DataFrame([log])], ignore_index=True)
                    
                    save_data(df_produtos, df_historico)
                    st.success("Cadastrado!")
                    st.rerun()

    # --- EXCLUSÃO ---
    st.write("---")
    with st.expander("🗑️ Excluir Produto do Sistema"):
        if not df_produtos.empty:
            p_del = st.selectbox("Selecione para excluir:", df_produtos['Produto'].unique(), key='del_sel')
            
            st.warning(f"Atenção: Isso removerá '{p_del}' da sua lista de sugestões e estoque permanentemente.")
            
            if st.button("Confirmar Exclusão"):
                # Remove do DataFrame de produtos
                df_produtos = df_produtos[df_produtos['Produto'] != p_del]
                
                # Salva alteração na planilha (sobrescreve a aba produtos)
                save_data(df_produtos, df_historico)
                
                st.error("Produto excluído!")
                time.sleep(1)
                st.rerun()
                
