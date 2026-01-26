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
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"
CHAT_ID = "1116977306"
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

# --- 🛑 COLE SUA CHAVE NOVA AQUI ---
GEMINI_KEY = "AIzaSyAeFpuANuD23TPbJO4l431bMjkOwCu8sRE"

bot = telebot.TeleBot(TOKEN)
ultimo_sinal_enviado = {} 

PADRAO_VIGILANCIA = ["PETR4.SA", "VALE3.SA", "BTC-USD", "ETH-USD"]

# LISTA TOP 40 (O Robô vai varrer TUDO isso aqui)
POOL_TOP_40 = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "WEGE3", "PRIO3", "RENT3", 
    "GGBR4", "SUZB3", "BPAC11", "EQTL3", "RADL3", "RAIL3", "RDOR3", "CMIG4", 
    "ELET3", "LREN3", "TOTS3", "CSAN3", "HAPV3", "VBBR3", "BBSE3", "GOAU4", 
    "MGLU3", "B3SA3", "TIMS3", "KLBN11", "ABEV3", "CPLE6", "EMBR3", "VIVT3",
    "JBSS3", "BRFS3", "CVCB3", "AZUL4", "PCAR3", "MRFG3", "GMAT3", "SBSP3"
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def pegar_dados_yahoo(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1mo", interval="15m")
        if df is None or df.empty: return None
        return df
    except: return None

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
    modelos = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash-latest"]
    erros_log = []
    
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                erros_log.append(f"{modelo}: {response.text}")
                continue
        except Exception as e:
            erros_log.append(f"{modelo}: {str(e)}")
            continue
            
    return f"⚠️ FALHA IA: Verifique a chave na linha 35.\nErro: {erros_log[0] if erros_log else '?'}"

# ==============================================================================
# 5. SCANNER TOP 40 (O "ASPIRADOR" DE AÇÕES) 🌪️
# ==============================================================================
def escanear_mercado_top40(apenas_fortes=False):
    """
    Varre os 40 ativos do Pool.
    Retorna uma lista de dicionários com Symbol, RSI e Tag.
    """
    oportunidades = []
    
    for simbolo in POOL_TOP_40:
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
                rsi = analise.indicators.get("RSI", 50)
                fechamento = analise.indicators.get("close", 0)
                oportunidades.append({
                    "texto": f"{simbolo} ({tag} | R$ {fechamento:.2f})",
                    "rsi": rsi,
                    "symbol": simbolo
                })
            time.sleep(0.1) # Breve pausa para não travar
        except: continue
        
    return oportunidades

def gerar_alocacao(valor):
    # 1. SCANNER: Pega TUDO que é compra nos 40 ativos
    raw_ops = escanear_mercado_top40(apenas_fortes=False)
    
    if not raw_ops: 
        return "⚠️ O Scanner varreu 40 ações e não achou tendências de alta claras hoje."
    
    # 2. FILTRAGEM: Pega os Top 15 com melhor RSI (mais saudáveis)
    # Isso garante que a IA olhe para uma gama grande, mas foque na qualidade
    top_15 = sorted(raw_ops, key=lambda x: x['rsi'], reverse=True)[:15]
    lista_para_ia = [x['texto'] for x in top_15]
    
    manchetes = []
    try:
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        for entry in d.entries[:3]: manchetes.append(entry.title)
    except: pass

    prompt = (
        f"Atue como Consultor de Investimentos (Robo-Advisor). Cliente tem R$ {valor} para investir. "
        f"Manchetes: {manchetes}. "
        f"O Scanner filtrou estas 15 Oportunidades (Top 40 Ibovespa): {', '.join(lista_para_ia)}. "
        f"TAREFA: "
        f"1) Escolha 3 ou 4 ativos dessa lista para montar uma carteira diversificada. "
        f"2) Distribua EXATAMENTE R$ {valor} entre eles. "
        f"3) Explique o racional. "
        f"Responda com lista e emojis."
    )
    return consultar_gemini(prompt)

def analisar_ativo_tecnico(ativo):
    try:
        df = pegar_dados_yahoo(ativo)
        if df is None: return "Erro dados Yahoo."
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        preco = df['Close'].iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        prompt = (
            f"Analise {ativo}. Preço: {preco:.2f} | RSI: {rsi:.1f} | "
            f"Médias 9/21: {sma9:.2f}/{sma21:.2f} ({tendencia}). "
            "Dê um veredito técnico curto: Compra, Venda ou Neutro?"
        )
        return consultar_gemini(prompt)
    except Exception as e: return f"Erro: {str(e)}"

# ==============================================================================
# 6. TELEGRAM HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Hunter (Top Oportunidades)", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("🎩 Consultor (Alocação)", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📂 Ver Portfólio", callback_data="CMD_PORTFOLIO"))
    
    txt = (
        "🤖 **QuantBot V45**\n\n"
        "Comandos Manuais:\n"
        "`/comprar ATIVO PRECO`\n"
        "`/vender ATIVO PRECO`\n"
        "`/analisar ATIVO` (IA)"
    )
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        partes = m.text.split()
        if len(partes) < 2: return bot.reply_to(m, "Use: `/analisar ATIVO`")
        atv = partes[1].upper()
        
        # Feedback visual para o usuário
        bot.send_chat_action(m.chat.id, 'typing')
        bot.reply_to(m, f"🔍 Analisando **{atv}** com IA... aguarde.")
        
        res = analisar_ativo_tecnico(atv)
        bot.reply_to(m, f"📊 **Análise {atv}**\n\n{res}", parse_mode="Markdown")
    except: pass

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
        msg = bot.send_message(c.message.chat.id, "💰 Quanto investir? (Ex: 5000)", reply_markup=ForceReply())
        bot.register_next_step_handler(msg, passo_consultor_valor)
    
    elif c.data == "CMD_PORTFOLIO":
        sh = conectar_google()
        try: 
            dados = sh.worksheet("Portfolio").get_all_values()[-5:]
            txt = "📂 **Últimos Registros:**\n"
            for row in dados: txt += f"{row[1]} | {row[2]} | {row[3]}\n"
            bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")
        except: bot.send_message(c.message.chat.id, "Portfólio vazio.")

    elif c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Varrendo Top 40...")
        bot.send_message(c.message.chat.id, "🔭 **Hunter:** Buscando oportunidades FORTES nos Top 40... (Aguarde ~40s)")
        threading.Thread(target=enviar_relatorio_agendado).start()

def passo_consultor_valor(message):
    try:
        valor = float(message.text.replace(",", ".").replace("R$", ""))
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(message, f"🤖 Analisando **Top 40** para alocar R$ {valor:.2f}...\n⏳ Aguarde ~45 segundos...")
        sugestao = gerar_alocacao(valor)
        bot.reply_to(message, f"🎩 **Sugestão:**\n\n{sugestao}", parse_mode="Markdown")
    except: bot.reply_to(message, "❌ Use números.")

# ==============================================================================
# 7. LOOP MONITORAMENTO (CARTEIRA PESSOAL)
# ==============================================================================
def loop():
    while True:
        try:
            lista_vigilancia = ler_carteira_vigilancia()
            for atv in lista_vigilancia:
                try:
                    df = pegar_dados_yahoo(atv)
                    if df is None: continue
                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    preco = df['Close'].iloc[-1]
                    preco_str = formatar_preco(preco)

                    sinal = None
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70): sinal = "COMPRA"
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev): sinal = "VENDA"
                    
                    if sinal:
                        chave = f"{atv}_{sinal}_{datetime.now().day}"
                        if chave not in ultimo_sinal_enviado:
                            markup = InlineKeyboardMarkup()
                            emoji = "🟢" if sinal == "COMPRA" else "🔴"
                            cb_real = f"REAL|{sinal}|{atv}|{preco_str}"
                            markup.add(InlineKeyboardButton(f"✅ Executar Real", callback_data=cb_real),
                                     InlineKeyboardButton(f"👀 Ciente", callback_data=f"SUGEST|{sinal}|{atv}|{preco_str}"))
                            bot.send_message(CHAT_ID, f"{emoji} **SINAL {sinal}**: {atv}\nPreço: {preco_str}", reply_markup=markup)
                            ultimo_sinal_enviado[chave] = True
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

# ==============================================================================
# 8. HUNTER (FILTRADO PARA FORTES)
# ==============================================================================
def executar_hunter_completo():
    sentimento = "Sem notícias."
    try:
        manchetes = []
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        for entry in d.entries[:4]: manchetes.append(entry.title)
        if manchetes:
            prompt = f"Resuma o sentimento do mercado em 2 linhas com base em: {manchetes}."
            sentimento = consultar_gemini(prompt)
    except: pass

    # Hunter só mostra STRONG_BUY para não poluir
    raw_ops = escanear_mercado_top40(apenas_fortes=True)
    achados = [x['texto'] for x in raw_ops]
    
    return sentimento, achados

def enviar_relatorio_agendado():
    humor, achados = executar_hunter_completo()
    txt_sinais = "\n".join(achados) if achados else "🚫 Sem 'Strong Buy' no momento."
    msg = f"🗞️ **MERCADO:**\n{humor}\n\n🔥 **OPORTUNIDADES FORTES:**\n{txt_sinais}"
    bot.send_message(CHAT_ID, msg)

def thread_agendamento():
    times = ["09:30", "13:00", "16:30"]
    for t in times: schedule.every().day.at(t).do(enviar_relatorio_agendado)
    while True: schedule.run_pending(); time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "QuantBot V45 (Chefão)"

if __name__ == "__main__":
    threading.Thread(target=loop).start()
    threading.Thread(target=thread_agendamento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()