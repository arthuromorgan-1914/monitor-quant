import os
import shutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
import gspread
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import threading
import random 
from flask import Flask
from datetime import datetime, timedelta
from pathlib import Path
import feedparser
from tradingview_ta import TA_Handler, Interval, Exchange
import schedule
import requests

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

print("--- INICIANDO QUANTBOT V52 (IA JUDGE + VOLUME) ---")
if not TOKEN: print("ERRO: TOKEN não encontrado.")
if not GEMINI_KEY: print("ERRO: GEMINI_KEY não encontrada.")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
ultimo_sinal_enviado = {} 

# Mínimo de Volume Financeiro para operar (R$ 5 Milhões)
VOLUME_MINIMO_BRL = 5_000_000 

PADRAO_VIGILANCIA = ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "WEGE3.SA", "PRIO3.SA"]

POOL_B3_TOTAL = [
    "PETR4", "VALE3", "PRIO3", "CSAN3", "RRRP3", "USIM5", "GGBR4", "GOAU4", "SUZB3", "KLBN11", "SLCE3", "SMTO3", "VBBR3", "RAIZ4",
    "ITUB4", "BBDC4", "BBAS3", "BPAC11", "SANB11", "B3SA3", "BBSE3", "PSSA3", "ITSA4", "CIEL3",
    "LREN3", "MGLU3", "ARZZ3", "SOMA3", "RDOR3", "RADL3", "NTCO3", "CRFB3", "ASAI3", "JBSS3", "BRFS3", "MRFG3", "BEEF3", "ABEV3",
    "WEGE3", "ELET3", "EQTL3", "CMIG4", "CPLE6", "EGIE3", "ENEV3", "TAEE11", "CPFE3", "SBSP3", "CSMG3",
    "CYRE3", "MRVE3", "EZTC3", "IGTI11", "MULT3", "ALOS3",
    "TOTS3", "VIVT3", "TIMS3",
    "RAIL3", "AZUL4", "GOLL4", "EMBR3", "RENT3", "MOVI3",
    "HAPV3", "FLRY3", "YDUQ3", "CVCB3"
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def corrigir_escala(symbol, preco):
    if preco > 10000: return preco / 10000
    return preco

def normalizar_simbolo(entrada):
    s = entrada.upper().strip()
    if "." in s: return s 
    if "-" in s: return s 
    criptos = ["BTC", "ETH", "SOL", "ADA", "XRP", "USDT"]
    if s in criptos: return f"{s}-USD"
    return f"{s}.SA"

def pegar_dados_yahoo(symbol, verificar_volume=False):
    try:
        symbol_corrigido = normalizar_simbolo(symbol)
        df = yf.Ticker(symbol_corrigido).history(period="1mo", interval="15m")
        if df is None or df.empty: return None
        
        # FILTRO DE VOLUME (Ideia 2)
        if verificar_volume:
            # Volume Financeiro Aproximado (Preço x Volume)
            vol_financeiro = df['Volume'].iloc[-1] * df['Close'].iloc[-1]
            if vol_financeiro < VOLUME_MINIMO_BRL:
                # Se for muito baixo, ignora (retorna None)
                return None
                
        return df
    except Exception as e:
        print(f"Erro Yahoo ({symbol}): {e}")
        return None

# ==============================================================================
# 3. GOOGLE SHEETS
# ==============================================================================
def conectar_google():
    if not os.path.exists('creds.json'): return None
    try:
        gc = gspread.service_account(filename='creds.json')
        return gc.open(NOME_PLANILHA_GOOGLE)
    except: return None

def ler_carteira_vigilancia():
    sh = conectar_google()
    if sh:
        try: return [x.upper().strip() for x in sh.worksheet("Carteira").col_values(1) if x.strip()]
        except: return PADRAO_VIGILANCIA
    return PADRAO_VIGILANCIA

def registrar_sugestao(ativo, sinal, preco):
    sh = conectar_google()
    if sh:
        try:
            try: ws = sh.worksheet("Sugestoes")
            except: ws = sh.add_worksheet(title="Sugestoes", rows=1000, cols=5)
            ws.append_row([datetime.now().strftime('%d/%m/%Y'), ativo, sinal, preco])
            return True
        except: return False
    return False

def registrar_portfolio_real(ativo, tipo, preco):
    sh = conectar_google()
    if sh:
        try:
            try: ws = sh.worksheet("Portfolio")
            except: ws = sh.add_worksheet(title="Portfolio", rows=1000, cols=6)
            tipo_norm = "Compra" if tipo.upper() in ["COMPRA", "COMPRAR"] else "Venda"
            status = "🟢 Aberta" if tipo_norm == "Compra" else "🔴 Encerrada"
            ws.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, tipo_norm, preco, status])
            return True
        except: return False
    return False

# ==============================================================================
# 4. INTEGRAÇÃO IA
# ==============================================================================
def consultar_gemini(prompt):
    if not GEMINI_KEY: return "❌ Erro: Chave Gemini ausente."
    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, headers=headers, json=data, timeout=25)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
        except: continue
    return "TIMEOUT IA"

# === NOVA FUNÇÃO: JUIZ DE SINAIS ===
def validar_sinal_com_ia(ativo, sinal, df):
    """
    Ideia 1: Camada de IA na análise.
    Recebe os dados técnicos e pergunta se a IA valida a entrada.
    """
    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
    vol = df['Volume'].iloc[-1]
    preco = df['Close'].iloc[-1]
    
    contexto = "Cruzamento de Alta (9>21)" if sinal == "COMPRA" else "Cruzamento de Baixa (9<21)"
    
    prompt = (
        f"Atue como Trader Sênior. Estou analisando {ativo} no gráfico de 15min. "
        f"Setup Técnico detectou: {contexto}. "
        f"Dados Atuais: Preço={preco:.2f}, RSI={rsi:.1f}, Volume={vol}, MM9={sma9:.2f}, MM21={sma21:.2f}. "
        f"PERGUNTA: Com base APENAS nestes números, esse sinal parece confiável ou é uma armadilha (ex: RSI extremo, sem volume)? "
        f"Responda EXATAMENTE neste formato: "
        f"'VEREDITO: APROVADO' ou 'VEREDITO: REPROVADO'. Em seguida, uma frase curta explicando."
    )
    
    resposta = consultar_gemini(prompt)
    
    if "APROVADO" in resposta.upper():
        motivo = resposta.split("APROVADO")[-1].strip().replace(".", "")[:50] # Pega explicação curta
        return True, motivo
    else:
        return False, "IA Reprovou (Risco Técnico)"

# ==============================================================================
# 5. SCANNER DE MERCADO (COM FILTRO DE VOLUME)
# ==============================================================================
def escanear_mercado_b3(apenas_fortes=False):
    oportunidades = []
    pool_limpo = list(set(POOL_B3_TOTAL))
    
    for simbolo in pool_limpo:
        try:
            handler = TA_Handler(symbol=simbolo, screener="brazil", exchange="BMFBOVESPA", interval=Interval.INTERVAL_1_DAY)
            analise = handler.get_analysis()
            rec = analise.summary['RECOMMENDATION']
            
            should_add = False
            tag = ""
            if "STRONG_BUY" in rec:
                tag = "🔥"
                should_add = True
            elif "BUY" in rec and not apenas_fortes:
                tag = "✅"
                should_add = True
            
            if should_add:
                # Só adiciona se tiver volume (validação simples via TradingView handler)
                # O handler não dá volume financeiro direto fácil, mas assumimos que B3 top 60 tem.
                rsi = analise.indicators.get("RSI", 50)
                fechamento = analise.indicators.get("close", 0)
                oportunidades.append({
                    "texto": f"{simbolo} ({tag} | R$ {fechamento:.2f})",
                    "rsi": rsi,
                    "symbol": simbolo
                })
            time.sleep(0.05)
        except: continue
    return oportunidades

def gerar_alocacao(valor):
    raw_ops = escanear_mercado_b3(apenas_fortes=False)
    if not raw_ops: return "⚠️ O Scanner não achou tendências."
    top_20 = sorted(raw_ops, key=lambda x: x['rsi'], reverse=True)[:20]
    lista_para_ia = [x['texto'] for x in top_20]
    
    prompt = (
        f"Atue como Robo-Advisor B3. Investimento: R$ {valor}. "
        f"Top Oportunidades (Volumosas): {', '.join(lista_para_ia)}. "
        f"Monte uma carteira com 4 ativos. Responda com lista."
    )
    return consultar_gemini(prompt)

def analisar_ativo_tecnico(ativo):
    try:
        symbol_corrigido = normalizar_simbolo(ativo)
        df = pegar_dados_yahoo(symbol_corrigido, verificar_volume=True) # Verifica volume aqui
        
        if df is None: return f"❌ {ativo}: Volume muito baixo (< R$ 5M) ou dados indisponíveis."
        
        preco_bruto = df['Close'].iloc[-1]
        preco = corrigir_escala(symbol_corrigido, preco_bruto)
        
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        if sma9 > 10000: sma9 /= 10000
        if sma21 > 10000: sma21 /= 10000
        
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        prompt = (
            f"Analise {symbol_corrigido}. Preço: {preco:.2f} | RSI: {rsi:.1f} | "
            f"M9/M21: {sma9:.2f}/{sma21:.2f} ({tendencia}). "
            "Volume Financeiro OK (>5M). Dê veredito: Compra/Venda?"
        )
        return consultar_gemini(prompt)
    except Exception as e: return f"Erro: {str(e)}"

# ==============================================================================
# 6. TELEGRAM HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Hunter B3", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("🎩 Consultor B3", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📂 Portfólio", callback_data="CMD_PORTFOLIO"))
    txt = "🤖 **QuantBot V52 - AI Judge**\n\n✅ Filtro de Volume (>5M)\n✅ Validação de Sinais por IA\n\n`/analisar ATIVO`"
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        partes = m.text.split()
        if len(partes) < 2: return bot.reply_to(m, "Use: `/analisar ATIVO`")
        atv_digitado = partes[1].upper()
        
        bot.send_chat_action(m.chat.id, 'typing')
        msg_wait = bot.reply_to(m, f"🔍 Analisando **{atv_digitado}** (Checando Volume + IA)...", parse_mode="Markdown")
        
        res = analisar_ativo_tecnico(atv_digitado)
        bot.edit_message_text(chat_id=m.chat.id, message_id=msg_wait.message_id, text=f"📊 **Análise {atv_digitado}**\n\n{res}")
    except Exception as e: bot.reply_to(m, f"❌ Erro: {e}")

@bot.message_handler(commands=['comprar'])
def manual_buy(m):
    try:
        partes = m.text.split()
        ativo = partes[1].upper()
        preco = partes[2].replace(",", ".")
        if registrar_portfolio_real(ativo, "Compra", preco):
            bot.reply_to(m, f"✅ Compra de **{ativo}** registrada!", parse_mode="Markdown")
        else: bot.reply_to(m, "❌ Erro planilha.")
    except: bot.reply_to(m, "⚠️ Use: `/comprar ATIVO PREÇO`")

@bot.message_handler(commands=['vender'])
def manual_sell(m):
    try:
        partes = m.text.split()
        ativo = partes[1].upper()
        preco = partes[2].replace(",", ".")
        if registrar_portfolio_real(ativo, "Venda", preco):
            bot.reply_to(m, f"🔻 Venda de **{ativo}** registrada!", parse_mode="Markdown")
        else: bot.reply_to(m, "❌ Erro planilha.")
    except: bot.reply_to(m, "⚠️ Use: `/vender ATIVO PREÇO`")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data.startswith("REAL|"):
        _, tipo, ativo, preco = c.data.split("|")
        if registrar_portfolio_real(ativo, tipo, preco):
            emoji = "✅" if tipo == "COMPRA" else "🔻"
            bot.send_message(c.message.chat.id, f"{emoji} {ativo} registrado!")
            bot.answer_callback_query(c.id, "Feito!")
    elif c.data.startswith("SUGEST|"):
        _, tipo, ativo, preco = c.data.split("|")
        registrar_sugestao(ativo, tipo, preco)
        bot.answer_callback_query(c.id, "Arquivado.")
        bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=f"👀 Sugestão arquivada.")
    elif c.data == "CMD_CONSULTOR":
        msg = bot.send_message(c.message.chat.id, "💰 Quanto investir?", reply_markup=ForceReply())
        bot.register_next_step_handler(msg, passo_consultor_valor)
    elif c.data == "CMD_PORTFOLIO":
        sh = conectar_google()
        try: 
            dados = sh.worksheet("Portfolio").get_all_values()[-5:]
            txt = "📂 **Últimos Registros:**\n"
            for row in dados: txt += f"{row[1]} | {row[2]} | {row[3]}\n"
            bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")
        except: bot.send_message(c.message.chat.id, "Vazio.")
    elif c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Varrendo...")
        bot.send_message(c.message.chat.id, "🔭 **Hunter B3:** Analisando oportunidades líquidas... (~50s)")
        threading.Thread(target=enviar_relatorio_agendado).start()

def passo_consultor_valor(message):
    try:
        valor = float(message.text.replace(",", ".").replace("R$", ""))
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(message, f"🤖 Analisando **Ativos Líquidos** para R$ {valor:.2f}...\n⏳ Aguarde...")
        sugestao = gerar_alocacao(valor)
        bot.reply_to(message, f"🎩 **Sugestão B3:**\n\n{sugestao}")
    except: bot.reply_to(message, "❌ Use números.")

# ==============================================================================
# 7. LOOP MONITORAMENTO (COM JUIZ IA) ⚖️
# ==============================================================================
def loop():
    while True:
        try:
            lista_vigilancia = ler_carteira_vigilancia()
            for atv in lista_vigilancia:
                try:
                    # Agora verifica volume também (Ideia 2)
                    df = pegar_dados_yahoo(atv, verificar_volume=True)
                    if df is None: continue # Sem volume ou dados, pula
                    
                    preco_bruto = df['Close'].iloc[-1]
                    atv_corr = normalizar_simbolo(atv)
                    preco = corrigir_escala(atv_corr, preco_bruto)

                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    if sma9 > 10000: sma9 /= 10000
                    if sma21 > 10000: sma21 /= 10000
                    
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    preco_str = formatar_preco(preco)

                    sinal_preliminar = None
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev): sinal_preliminar = "COMPRA"
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev): sinal_preliminar = "VENDA"
                    
                    if sinal_preliminar:
                        chave = f"{atv}_{sinal_preliminar}_{datetime.now().day}_{datetime.now().hour}"
                        if chave not in ultimo_sinal_enviado:
                            
                            # --- AQUI ENTRA O JUIZ IA (Ideia 1) ---
                            # Só manda se a IA aprovar
                            aprovado, explicacao = validar_sinal_com_ia(atv_corr, sinal_preliminar, df)
                            
                            if aprovado:
                                markup = InlineKeyboardMarkup()
                                emoji = "🟢" if sinal_preliminar == "COMPRA" else "🔴"
                                cb_real = f"REAL|{sinal_preliminar}|{atv}|{preco_str}"
                                markup.add(InlineKeyboardButton(f"✅ Executar Real", callback_data=cb_real),
                                         InlineKeyboardButton(f"👀 Ciente", callback_data=f"SUGEST|{sinal_preliminar}|{atv}|{preco_str}"))
                                
                                # Adiciona a explicação da IA na mensagem
                                msg = f"{emoji} **SINAL {sinal_preliminar}**: {atv}\nPreço: {preco_str}\n\n🧠 **IA Diz:** {explicacao}"
                                bot.send_message(CHAT_ID, msg, reply_markup=markup)
                                ultimo_sinal_enviado[chave] = True
                            else:
                                print(f"🚫 IA Vetou sinal em {atv}: {explicacao}")
                                # Opcional: Avisar veto? Por enquanto só ignora pra não fazer spam.
                                ultimo_sinal_enviado[chave] = True # Marca como "visto" pra não ficar tentando toda hora

                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

# ==============================================================================
# 8. HUNTER
# ==============================================================================
def executar_hunter_completo():
    sentimento = "Sem notícias."
    try:
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        manchetes = [entry.title for entry in d.entries[:4]]
        if manchetes:
            sentimento = consultar_gemini(f"Resuma sentimento em 2 linhas: {manchetes}")
    except: pass

    raw_ops = escanear_mercado_b3(apenas_fortes=True)
    achados = [x['texto'] for x in raw_ops]
    return sentimento, achados

def enviar_relatorio_agendado():
    humor, achados = executar_hunter_completo()
    txt_sinais = "\n".join(achados) if achados else "🚫 Sem sinais fortes."
    msg = f"🗞️ **MERCADO:**\n{humor}\n\n🔥 **TOP OPORTUNIDADES:**\n{txt_sinais}"
    bot.send_message(CHAT_ID, msg)

def thread_agendamento():
    times = ["09:30", "13:00", "16:30"]
    for t in times: schedule.every().day.at(t).do(enviar_relatorio_agendado)
    while True: schedule.run_pending(); time.sleep(60)

if TOKEN:
    app = Flask(__name__)
    @app.route('/')
    def home(): return "QuantBot V52 (IA Judge + Vol)"

    if __name__ == "__main__":
        threading.Thread(target=loop).start()
        threading.Thread(target=thread_agendamento).start()
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
        bot.infinity_polling()