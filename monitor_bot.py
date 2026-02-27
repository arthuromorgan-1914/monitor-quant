import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
import gspread
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import threading
from flask import Flask
from datetime import datetime
from tradingview_ta import TA_Handler, Interval

# ==============================================================================
# 1. CONFIGURAÇÕES (CUSTO ZERO - 100% B3)
# ==============================================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

print("--- INICIANDO QUANTBOT V62 (100% B3 + AUDITOR) ---")
if not TOKEN: print("ERRO: TOKEN não encontrado.")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
ultimo_sinal_enviado = {} 
VOLUME_MINIMO_BRL = 5_000_000 

# ==============================================================================
# 2. POOL DE ATIVOS DA B3 (75 ATIVOS SELECIONADOS)
# ==============================================================================
POOL_B3 = [
    # Bancos e Financeiros
    "ITUB4.SA", "BBDC4.SA", "BBAS3.SA", "SANB11.SA", "BPAC11.SA", "BBSE3.SA", "B3SA3.SA", "PSSA3.SA", "CXSE3.SA",
    # Petróleo, Gás e Combustíveis
    "PETR4.SA", "PETR3.SA", "PRIO3.SA", "RRRP3.SA", "CSAN3.SA", "VBBR3.SA", "UGPA3.SA", "RAIZ4.SA", "RECV3.SA",
    # Mineração e Siderurgia
    "VALE3.SA", "GGBR4.SA", "GOAU4.SA", "USIM5.SA", "CSNA3.SA", "CMIN3.SA",
    # Energia e Saneamento
    "ELET3.SA", "ELET6.SA", "EQTL3.SA", "CMIG4.SA", "CPLE6.SA", "TAEE11.SA", "TRPL4.SA", "EGIE3.SA", "CPFE3.SA", "SBSP3.SA", "CSMG3.SA",
    # Varejo e Consumo
    "LREN3.SA", "MGLU3.SA", "ARZZ3.SA", "SOMA3.SA", "ASAI3.SA", "CRFB3.SA", "NTCO3.SA", "CEAB3.SA",
    # Saúde e Farmácia
    "RADL3.SA", "HYPE3.SA", "FLRY3.SA", "HAPV3.SA", "RDOR3.SA",
    # Indústria, Transporte e Logística
    "WEGE3.SA", "EMBR3.SA", "AZUL4.SA", "GOLL4.SA", "RAIL3.SA", "CCRO3.SA", "POMO4.SA", "RENT3.SA",
    # Proteína, Alimentos e Agro
    "JBSS3.SA", "MRFG3.SA", "BEEF3.SA", "BRFS3.SA", "SMTO3.SA", "SLCE3.SA",
    # Shoppings e Construção
    "CYRE3.SA", "EZTC3.SA", "MRVE3.SA", "IGTI11.SA", "MULT3.SA", "ALOS3.SA",
    # Telecomunicações e Tecnologia
    "VIVT3.SA", "TIMS3.SA", "TOTS3.SA"
]

# ==============================================================================
# 3. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def corrigir_escala(preco):
    # Ações B3 raramente passam de R$ 300. Se passar de 10k, é erro do Yahoo.
    if preco > 10000: return preco / 10000
    return preco

def normalizar_simbolo(entrada):
    s = entrada.upper().strip()
    if "." in s: return s 
    if len(s) <= 6 and s[-1].isdigit(): return f"{s}.SA"
    return f"{s}.SA"

def gerar_link_apple(ativo):
    return f"https://stocks.apple.com/symbol/{ativo}"

def pegar_dados_yahoo(symbol, verificar_volume=True):
    try:
        symbol_corrigido = normalizar_simbolo(symbol)
        df = yf.Ticker(symbol_corrigido).history(period="1mo", interval="15m")
        if df is None or df.empty: return None
        
        # Filtro de Volume Financeiro Diário
        if verificar_volume:
            vol_financeiro = df['Volume'].iloc[-1] * df['Close'].iloc[-1]
            if vol_financeiro < VOLUME_MINIMO_BRL: return None
        return df
    except: return None

# ==============================================================================
# 4. GOOGLE SHEETS E AUDITORIA
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
        except: return POOL_B3 # Por padrão, vigia todos se a aba falhar
    return POOL_B3

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

def registrar_auditoria(ativo, sinal, preco_robo, preco_user):
    sh = conectar_google()
    if sh:
        try:
            try: ws = sh.worksheet("Auditoria")
            except: 
                ws = sh.add_worksheet(title="Auditoria", rows=1000, cols=6)
                ws.append_row(["Data", "Ativo", "Sinal", "Preço Robô", "Preço Nubank", "Diferença"])
            
            diferenca = round(preco_user - preco_robo, 4)
            ws.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, sinal, preco_robo, preco_user, diferenca])
            return diferenca
        except: return None
    return None

# ==============================================================================
# 5. ESTRATÉGIA MATEMÁTICA B3 (O CÉREBRO)
# ==============================================================================
def estrategia_b3(df):
    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
    
    if sma9 > 10000: sma9 /= 10000
    if sma21 > 10000: sma21 /= 10000

    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70): return "COMPRA"
    elif (sma9 < sma21) and (sma9_prev >= sma21_prev): return "VENDA"
    return None

# ==============================================================================
# 6. TELEGRAM HANDLERS E AUDITORIA
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📂 Portfólio", callback_data="CMD_PORTFOLIO"))
    txt = "🤖 **QuantBot V62 - B3 Exclusive**\n\nMonitorando 75 Ativos Líquidos da Bolsa BR.\nModo: Matemática Pura (Custo Zero)."
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data.startswith("REAL|"):
        _, tipo, atv, prc = c.data.split("|")
        registrar_portfolio_real(atv, tipo, prc)
        bot.answer_callback_query(c.id, "Feito!")
        bot.send_message(c.message.chat.id, f"✅ {atv} salvo no Portfólio!")
        
    elif c.data.startswith("AUDIT|"):
        _, sinal, ativo, preco_robo_str = c.data.split("|")
        msg = bot.send_message(
            c.message.chat.id, 
            f"⚖️ **Auditoria {ativo}**\nPreço do Robô foi: R$ {preco_robo_str}\n\nQual o preço exato que você está vendo no Nubank agora?", 
            reply_markup=ForceReply(),
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, passo_auditoria, ativo, sinal, preco_robo_str)
        
    elif c.data == "CMD_PORTFOLIO":
        sh = conectar_google()
        try: 
            dados = sh.worksheet("Portfolio").get_all_values()[-5:]
            txt = "📂 **Últimos:**\n"
            for row in dados: txt += f"{row[1]} | {row[2]} | {row[3]}\n"
            bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")
        except: bot.send_message(c.message.chat.id, "Vazio.")

def passo_auditoria(message, ativo, sinal, preco_robo_str):
    try:
        preco_user = float(message.text.replace(",", ".").replace("R$", "").strip())
        preco_robo = float(preco_robo_str.replace(",", "."))
        
        diff = registrar_auditoria(ativo, sinal, preco_robo, preco_user)
        
        if diff is not None:
            txt = f"✅ Auditoria salva na planilha!\n\nDiferença Nubank vs Robô: **R$ {diff:.2f}**"
            bot.reply_to(message, txt, parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ Erro ao salvar na planilha.")
    except Exception as e:
        bot.reply_to(message, "❌ Erro. Digite apenas números (ex: 38.50).")

# ==============================================================================
# 7. LOOP PRINCIPAL DE VARREDURA
# ==============================================================================
def loop():
    while True:
        try:
            lista = ler_carteira_vigilancia()
            for atv in lista:
                try:
                    atv_corr = normalizar_simbolo(atv)
                    df = pegar_dados_yahoo(atv_corr, verificar_volume=True)
                    if df is None: continue
                    
                    preco_bruto = df['Close'].iloc[-1]
                    preco = corrigir_escala(preco_bruto)
                    preco_str = formatar_preco(preco)

                    sinal = estrategia_b3(df)
                    
                    if sinal:
                        chave = f"{atv_corr}_{sinal}_{datetime.now().day}_{datetime.now().hour}_{datetime.now().minute//15}"
                        if chave not in ultimo_sinal_enviado:
                            
                            mk = InlineKeyboardMarkup()
                            mk.add(InlineKeyboardButton("✅ Executar Real", callback_data=f"REAL|{sinal}|{atv_corr}|{preco_str}"))
                            mk.add(InlineKeyboardButton(" App Bolsa", url=gerar_link_apple(atv_corr)))
                            mk.add(InlineKeyboardButton("⚖️ Informar Preço Nubank", callback_data=f"AUDIT|{sinal}|{atv_corr}|{preco_str}"))
                            
                            emoji = "🟢" if sinal == "COMPRA" else "🔴"
                            txt = f"{emoji} **SINAL {sinal}**: {atv_corr}\n⏱ Preço Base (Robô): R$ {preco_str}\n\n*Análise Matemática Pura confirmada.*"
                            
                            bot.send_message(CHAT_ID, txt, reply_markup=mk, parse_mode="Markdown")
                            ultimo_sinal_enviado[chave] = True
                            
                    time.sleep(1) # Pausa curta entre ativos para não sobrecarregar
                except: pass
            time.sleep(900) # Pausa de 15 minutos até a próxima varredura
        except: time.sleep(60)

if TOKEN:
    app = Flask(__name__)
    @app.route('/')
    def home(): return "QuantBot V62 (B3 100% - Auditor)"
    if __name__ == "__main__":
        threading.Thread(target=loop).start()
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
        bot.infinity_polling()