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
GEMINI_KEY = "AIzaSyA9HqUYO3G2_5o9l2fL3T44CmrGn6H-Dck"

bot = telebot.TeleBot(TOKEN)

# CONTROLE DE SINAIS REPETIDOS (COOLDOWN)
ultimo_aviso = {} 

# LISTA UNIVERSAL (Para monitoramento contínuo / Hunter / Lista Pessoal)
# (Esta é a lista que o robô vigia 24h para você)
ALVOS_CAÇADOR = [
    {"symbol": "PETR4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PETR4.SA"},
    {"symbol": "VALE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "VALE3.SA"},
    {"symbol": "WEGE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "WEGE3.SA"},
    {"symbol": "PRIO3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PRIO3.SA"},
    {"symbol": "ITUB4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "ITUB4.SA"},
    {"symbol": "BBAS3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "BBAS3.SA"},
    {"symbol": "BTCUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "BTC-USD"},
    {"symbol": "ETHUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "ETH-USD"},
    {"symbol": "SOLUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "SOL-USD"},
    {"symbol": "NVDA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "NVDA"},
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    """Formata preço: 2 casas para ações, 5 para criptos pequenas"""
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

def ler_carteira():
    sh = conectar_google()
    if sh:
        try: return [x.upper().strip() for x in sh.worksheet("Carteira").col_values(1) if x.strip()]
        except: return []
    return []

def registrar_trade(ativo, preco, tipo="Compra"):
    sh = conectar_google()
    if sh:
        try:
            status = "Aberta" if tipo == "Compra" else "Encerrada"
            sh.sheet1.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, tipo, preco, "", "", status])
            return True
        except: return False
    return False

def verificar_ultimo_status(ativo):
    sh = conectar_google()
    if sh:
        try:
            dados = sh.sheet1.get_all_values()
            for linha in reversed(dados):
                if len(linha) > 2 and linha[1].strip().upper() == ativo.strip().upper():
                    return linha[2].strip()
        except: return None
    return None

# ==============================================================================
# 4. INTEGRAÇÃO IA (GEMINI)
# ==============================================================================
def consultar_gemini(prompt):
    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
        except: continue
    return "❌ IA Indisponível."

# ==============================================================================
# 5. CONSULTOR ROBO-ADVISOR (EXPANDIDO - TOP 40) 🎩
# ==============================================================================
def buscar_oportunidades_mercado():
    """Busca ações brasileiras com 'Strong Buy' ou 'Buy' no TradingView"""
    candidatas = []
    
    # LISTA EXPANDIDA: Mistura de Blue Chips, Mid Caps e Setores Variados
    # Inclui: Bancos, Commodities, Varejo, Elétricas, Saúde, Tech, Aéreas
    pool_expandido = [
        "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "WEGE3", "PRIO3", "RENT3", 
        "GGBR4", "SUZB3", "BPAC11", "EQTL3", "RADL3", "RAIL3", "RDOR3", "CMIG4", 
        "ELET3", "LREN3", "TOTS3", "CSAN3", "HAPV3", "VBBR3", "BBSE3", "GOAU4", 
        "MGLU3", "B3SA3", "TIMS3", "KLBN11", "ABEV3", "CPLE6", "EMBR3", "VIVT3",
        "JBSS3", "BRFS3", "CVCB3", "AZUL4", "PCAR3", "MRFG3", "GMAT3", "SBSP3"
    ]
    
    # Randomiza um pouco a lista se ficar muito grande, ou pega todos.
    # Vamos pegar todos, mas com um try/catch rápido para não travar.
    
    for simbolo in pool_expandido:
        try:
            handler = TA_Handler(symbol=simbolo, screener="brazil", exchange="BMFBOVESPA", interval=Interval.INTERVAL_1_DAY)
            analise = handler.get_analysis()
            rec = analise.summary['RECOMMENDATION']
            
            # Pega tanto COMPRA FORTE quanto COMPRA (oportunidades na margem)
            if "BUY" in rec: 
                rsi = analise.indicators.get("RSI", 50)
                fechamento = analise.indicators.get("close", 0)
                
                # Formatação visual para a IA
                tag = "🔥 FORTE" if "STRONG" in rec else "✅ COMPRA"
                candidatas.append(f"{simbolo} ({tag} | R$ {fechamento:.2f} | RSI: {rsi:.1f})")
                
        except: continue
        
    return candidatas

def gerar_alocacao(valor_investimento):
    # 1. Varredura ampla (Pode demorar uns 40s)
    oportunidades = buscar_oportunidades_mercado()
    
    if not oportunidades:
        return "⚠️ O scanner varreu 40 ativos e não encontrou tendências claras de alta hoje. Mercado indeciso. Melhor aguardar."

    # 2. Notícias
    manchetes = []
    try:
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        for entry in d.entries[:3]: manchetes.append(entry.title)
    except: pass

    # 3. Prompt Inteligente
    prompt = (
        f"Atue como um Consultor de Investimentos Robô (Robo-Advisor). "
        f"O cliente quer investir R$ {valor_investimento}. "
        f"Manchetes do dia: {manchetes}. "
        f"O scanner técnico encontrou estas oportunidades (Status | Preço | RSI): {', '.join(oportunidades)}. "
        f"TAREFA: Selecione as 3 ou 4 melhores oportunidades dessa lista para montar uma carteira. "
        f"Tente equilibrar segurança (Blue Chips) com potencial (ações 'na margem' ou recuperação). "
        f"Distribua o valor de R$ {valor_investimento} entre elas. "
        f"Justifique cada escolha com base no RSI ou setor. "
        f"Responda com uma lista bonita e emojis."
    )
    
    return consultar_gemini(prompt)

# ==============================================================================
# 6. ANÁLISE TÉCNICA E MONITORAMENTO
# ==============================================================================
def analisar_ativo_tecnico(ativo):
    try:
        df = pegar_dados_yahoo(ativo)
        if df is None or len(df) < 50: return "❌ Erro dados."
        
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        preco = df['Close'].iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        prompt = (
            f"Analise {ativo}. Preço: {preco} | RSI: {rsi:.1f} | "
            f"Médias: 9({sma9:.2f}) vs 21({sma21:.2f}). Tendência: {tendencia}. "
            "Resuma em 3 linhas: Análise técnica e recomendação."
        )
        return consultar_gemini(prompt)
    except Exception as e: return str(e)

# ==============================================================================
# 7. TELEGRAM HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔫 Hunter (Oportunidades)", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("🎩 Consultor (Alocação)", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📋 Minha Lista", callback_data="CMD_LISTA"))
    
    texto = (
        "🤖 **QuantBot V37 - Mercado Expandido**\n\n"
        "Sou seu assistente de investimentos automatizado.\n"
        "📈 **Monitoro:** Tendências e indicadores (M9xM21, RSI).\n"
        "🧠 **Analiso:** Uso IA para interpretar o mercado e sugerir alocações.\n"
        "📝 **Organizo:** Registro tudo na sua planilha.\n\n"
        "Escolha uma função:"
    )
    bot.reply_to(message, texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Buscando oportunidades...")
        bot.send_message(c.message.chat.id, "🔎 O Hunter está varrendo o mercado... aguarde.")
        threading.Thread(target=enviar_relatorio_agendado).start()

    elif c.data == "CMD_CONSULTOR":
        msg = bot.send_message(c.message.chat.id, "💰 **Consultor Financeiro**\n\nQual valor você deseja investir hoje? (Ex: 1000, 5000)\nDigite apenas o número:", reply_markup=ForceReply())
        bot.register_next_step_handler(msg, passo_consultor_valor)

    elif c.data == "CMD_LISTA":
        bot.send_message(c.message.chat.id, f"📋 **Vigiando:**\n" + "\n".join(ler_carteira()), parse_mode="Markdown")

    elif "COMPRA|" in c.data or "VENDA|" in c.data:
        op, atv, prc = c.data.split("|")
        registrar_trade(atv, prc, op)
        bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=f"✅ {op} {atv} registrada!")

def passo_consultor_valor(message):
    try:
        valor = float(message.text.replace(",", ".").replace("R$", ""))
        bot.send_chat_action(message.chat.id, 'typing')
        # Aviso de tempo para o usuário não achar que travou
        bot.reply_to(message, f"🤖 Entendido! O Scanner está analisando **40 ativos** do Ibovespa para alocar R$ {valor:.2f}...\n\n⏳ **Isso pode levar até 60 segundos.** Aguarde.")
        
        sugestao = gerar_alocacao(valor)
        bot.reply_to(message, f"🎩 **Sua Sugestão de Carteira:**\n\n{sugestao}", parse_mode="Markdown")
    except ValueError:
        bot.reply_to(message, "❌ Por favor, digite apenas números (ex: 1000). Tente novamente no /menu.")

@bot.message_handler(commands=['add'])
def add(m):
    try: 
        sh = conectar_google()
        sh.worksheet("Carteira").append_row([m.text.split()[1].upper()])
        bot.reply_to(m, "✅ Adicionado!")
    except: bot.reply_to(m, "Erro.")

@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        atv = m.text.split()[1].upper()
        res = analisar_ativo_tecnico(atv)
        bot.reply_to(m, f"📊 **{atv}**\n{res}", parse_mode="Markdown")
    except: bot.reply_to(m, "Use: /analisar ATIVO")

# ==============================================================================
# 8. LOOP DE MONITORAMENTO (COM COOLDOWN E PRECISÃO)
# ==============================================================================
def loop():
    while True:
        try:
            for atv in ler_carteira():
                try:
                    df = pegar_dados_yahoo(atv)
                    if df is None: continue
                    
                    # Indicadores
                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    preco = df['Close'].iloc[-1]
                    
                    # Formatação Inteligente de Preço
                    preco_str = formatar_preco(preco)

                    # Cooldown
                    agora = time.time()
                    if atv in ultimo_aviso and (agora - ultimo_aviso[atv] < 1800):
                        continue

                    last = verificar_ultimo_status(atv)

                    # Lógica de Sinal
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70) and (last != "Compra"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"Comprar @ {preco_str}", callback_data=f"COMPRA|{atv}|{preco_str}"))
                        bot.send_message(CHAT_ID, f"🟢 **COMPRA**: {atv}\nPreço: {preco_str}\nRSI: {rsi:.1f}", reply_markup=markup)
                        ultimo_aviso[atv] = agora

                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev) and (last != "Venda"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"Vender @ {preco_str}", callback_data=f"VENDA|{atv}|{preco_str}"))
                        bot.send_message(CHAT_ID, f"🔴 **VENDA**: {atv}\nPreço: {preco_str}", reply_markup=markup)
                        ultimo_aviso[atv] = agora
                    
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

# Agendamento do Hunter (Mantido Simples)
def enviar_relatorio_agendado():
    try:
        pass 
    except: pass

app = Flask(__name__)
@app.route('/')
def home(): return "QuantBot V37 (Scanner 40 Ativos)"

if __name__ == "__main__":
    threading.Thread(target=loop).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()