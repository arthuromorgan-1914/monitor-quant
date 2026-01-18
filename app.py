import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mentor Quant - Global Scanner", layout="wide")
st.title("🌍 Mentor Quant - Scanner de Portfólio Global")
st.markdown("Analise Ações BR, Stocks Americanas e Cripto no mesmo ranking.")

# --- LISTAS PRÉ-DEFINIDAS (MACROS) ---
# Você pode aumentar essas listas depois
TOP_BR = "VALE3.SA, PETR4.SA, ITUB4.SA, BBDC4.SA, BBAS3.SA, WEGE3.SA, ELET3.SA, RENT3.SA, PRIO3.SA, BPAC11.SA"
TOP_CRYPTO = "BTC-USD, ETH-USD, SOL-USD, BNB-USD"
TOP_US = "AAPL, MSFT, GOOG, AMZN, TSLA, NVDA, AMD"

# --- GERENCIAMENTO DE ESTADO (MEMÓRIA) ---
# Isso garante que o campo de texto não "resete" quando você clica nos botões
if 'lista_ativos' not in st.session_state:
    st.session_state['lista_ativos'] = "PETR4.SA, VALE3.SA, BTC-USD"

# Funções de Callback (O que acontece quando clica nos botões)
def add_br():
    st.session_state['lista_ativos'] = TOP_BR
def add_crypto():
    current = st.session_state['lista_ativos']
    if current:
        st.session_state['lista_ativos'] = current + ", " + TOP_CRYPTO
    else:
        st.session_state['lista_ativos'] = TOP_CRYPTO
def add_us():
    current = st.session_state['lista_ativos']
    if current:
        st.session_state['lista_ativos'] = current + ", " + TOP_US
    else:
        st.session_state['lista_ativos'] = TOP_US
def limpar():
    st.session_state['lista_ativos'] = ""

# --- BARRA LATERAL (CONTROLES) ---
with st.sidebar:
    st.header("Montagem de Carteira")
    
    st.markdown("### 1. Atalhos Rápidos")
    col1, col2 = st.columns(2)
    with col1:
        st.button("🇧🇷 Top 10 Brasil", on_click=add_br, use_container_width=True)
        st.button("🇺🇸 Big Techs EUA", on_click=add_us, use_container_width=True)
    with col2:
        st.button("₿ Cripto", on_click=add_crypto, use_container_width=True)
        st.button("🗑️ Limpar Tudo", on_click=limpar, use_container_width=True)

    st.markdown("### 2. Edição Fina")
    # O "key='lista_ativos'" conecta essa caixa à memória do sistema
    ativos_input = st.text_area("Edite sua lista final aqui:", height=150, key='lista_ativos')
    
    st.markdown("---")
    data_inicio = st.date_input("Data de Início", pd.to_datetime("2024-01-01"))
    botao_scan = st.button("🚀 Escanear Mercado", type="primary")

# --- FUNÇÃO DE ANÁLISE (MOTOR) ---
def analisar_ativo(ativo, inicio):
    try:
        df = yf.download(ativo, start=inicio, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        
        if len(df) < 60: return None

        melhor_resultado = -9999
        best_config = (0, 0)
        
        # Otimização (Solver)
        for lenta in range(20, 55, 10):
            for rapida in range(5, 16, 5):
                if rapida >= lenta: continue
                
                df_t = df.copy()
                df_t['Fast'] = ta.sma(df_t['Close'], length=rapida)
                df_t['Slow'] = ta.sma(df_t['Close'], length=lenta)
                df_t['Sinal'] = 0
                df_t.loc[df_t['Fast'] > df_t['Slow'], 'Sinal'] = 1
                
                df_t['Retorno'] = df_t['Close'].pct_change()
                df_t['Strat'] = df_t['Retorno'] * df_t['Sinal'].shift(1)
                res = (1 + df_t['Strat']).cumprod().iloc[-1]
                
                if res > melhor_resultado:
                    melhor_resultado = res
                    best_config = (rapida, lenta)
        
        # Status Hoje
        df['Fast'] = ta.sma(df['Close'], length=best_config[0])
        df['Slow'] = ta.sma(df['Close'], length=best_config[1])
        ultimo_sinal = "COMPRA 🟢" if df['Fast'].iloc[-1] > df['Slow'].iloc[-1] else "NEUTRO/VENDA 🔴"
        
        lucro_pct = (melhor_resultado - 1) * 100
        
        return {
            "Ativo": ativo,
            "Melhor Setup": f"{best_config[0]}/{best_config[1]}",
            "Lucro Período": lucro_pct,
            "Status Hoje": ultimo_sinal,
            "Preço Atual": df['Close'].iloc[-1]
        }
        
    except:
        return None

# --- EXECUÇÃO ---
if botao_scan:
    # Limpeza da lista (remove espaços extras e itens vazios)
    lista_ativos = [x.strip() for x in ativos_input.split(',') if x.strip()]
    
    if not lista_ativos:
        st.warning("Sua lista está vazia! Adicione ativos ou use os botões de atalho.")
    else:
        resultados = []
        barra = st.progress(0)
        status_text = st.empty()
        
        for i, ativo in enumerate(lista_ativos):
            status_text.text(f"Auditando {ativo} ({i+1}/{len(lista_ativos)})...")
            barra.progress((i + 1) / len(lista_ativos))
            
            res = analisar_ativo(ativo, data_inicio)
            if res:
                resultados.append(res)
                
        barra.empty()
        status_text.empty()
        
        if resultados:
            df_res = pd.DataFrame(resultados)
            df_res = df_res.sort_values(by="Lucro Período", ascending=False)
            
            st.subheader(f"🏆 Resultado do Scan ({len(resultados)} ativos)")
            
            st.dataframe(
                df_res,
                column_config={
                    "Lucro Período": st.column_config.NumberColumn(format="%.2f %%"),
                    "Preço Atual": st.column_config.NumberColumn(format="%.2f"),
                    "Status Hoje": st.column_config.TextColumn(help="Sinal baseado no melhor setup histórico")
                },
                hide_index=True,
                use_container_width=True
            )
            
            # Insights Automáticos
            vencedor = df_res.iloc[0]
            st.success(f"💎 **Oportunidade Ouro:** O melhor ativo é **{vencedor['Ativo']}** com potencial de **{vencedor['Lucro Período']:.2f}%**.")
            
            # Conta quantos estão dando compra
            compras = df_res[df_res['Status Hoje'].str.contains("COMPRA")]
            st.info(f"📊 Resumo de Mercado: De {len(resultados)} ativos analisados, **{len(compras)}** estão em tendência de alta agora.")
            
        else:
            st.error("Não foi possível analisar os ativos. Verifique os códigos digitados.")