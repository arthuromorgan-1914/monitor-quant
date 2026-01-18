import os
import shutil
import requests
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import random
import threading
from flask import Flask
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. O TRUQUE DO SITE FANTASMA (Para o Render não desligar)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Estou Vivo! O Robô está trabalhando."

def run_server():
    # Pega a porta que o Render exige ou usa a 5000 se for local
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def iniciar_servidor_fake():
    # Roda o servidor numa linha paralela (thread) para não travar o robô
    t = threading.Thread(target=run_server)
    t.start()

# ==============================================================================
# 2. CONFIGURAÇÕES PESSOAIS
# ==============================================================================
# ⚠️ ATENÇÃO: COLOQUE SEU TOKEN E CHAT_ID AQUI DE NOVO!
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"      # <--- CONFIRA SEU TOKEN (Não esqueça de colocar de novo!)
CHAT_ID = "1116977306"  # <--- CONFIRA SEU ID-+9

CARTEIRA = [
    "BTC-USD", "ETH-USD", "SOL-USD", 
    "PETR4.SA", "VALE3.SA", "WEGE3.SA", "PRIO3.SA",
    "AAPL", "NVDA", "MSFT", "TSLA"
]

INTERVALO_VARREDURA = 60 # Minutos

# ==============================================================================
# 3. LÓGICA DO ROBÔ
# ==============================================================================
def criar_sessao_disfarce():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def limpar_cache_yahoo():
    try:
        cache_path = Path.home() / ".cache" / "py-yfinance"
        if cache_path.exists():
            shutil.rmtree(cache_path)
            print("🧹 Cache deletado.")
    except Exception:
        pass

def enviar_telegram(mensagem):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": mensagem, "disable_web_page_preview": True}
        requests.post(url, data=data)
    except Exception as e:
        print(f"❌ Erro Telegram: {e}")

def analisar_mercado():
    limpar_cache_yahoo()
    hora_atual = datetime.now().strftime('%H:%M')
    print(f"\n--- Iniciando Varredura ({hora_atual}) ---")
    
    sessao_fake = criar_sessao_disfarce()
    msg_relatorio = f"🔍 Monitor Cloud ({hora_atual})\n\n"
    oportunidades = 0

    for ativo in CARTEIRA:
        try:
            ticker = yf.Ticker(ativo, session=sessao_fake)
            df = ticker.history(period="6mo")
            
            if df.empty: 
                ticker = yf.Ticker(ativo)
                df = ticker.history(period="6mo")

            if df.empty or len(df) < 22: continue
            
            # Estratégia: Média 9 cruzando Média 21
            media_curta = ta.sma(df['Close'], length=9).iloc[-1]
            media_longa = ta.sma(df['Close'], length=21).iloc[-1]
            preco_atual = df['Close'].iloc[-1]
            
            if media_curta > media_longa:
                oportunidades += 1
                var_dia = ((preco_atual - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
                msg_relatorio += f"🟢 {ativo} | {preco_atual:.2f} ({var_dia:+.1f}%)\n"
                print(f"✅ {ativo}: ALTA")
            
            time.sleep(random.randint(2, 5)) 

        except Exception as e:
            print(f"❌ Erro {ativo}: {e}")

    # --- AQUI ESTÁ A MUDANÇA (HEARTBEAT) ---
    if oportunidades > 0:
        msg_relatorio += "\n🚀 Verifique o Gráfico!"
        enviar_telegram(msg_relatorio)
    else:
        # Agora ele avisa que está vivo, mesmo sem oportunidades
        msg_quiet = f"📉 Status ({hora_atual}): Mercado lateral.\nNenhuma entrada agora, mas sigo vigiando."
        enviar_telegram(msg_quiet)

# ==============================================================================
# 4. EXECUÇÃO FINAL
# ==============================================================================
if __name__ == "__main__":
    iniciar_servidor_fake()
    
    print("✅ Robô Iniciado (Modo Tagarela)!")
    enviar_telegram("🤖 Atualização Recebida!\nAgora avisarei a cada 60min, aconteça o que acontecer.")

    while True:
        analisar_mercado()
        print(f"Dormindo por {INTERVALO_VARREDURA} minutos...")
        time.sleep(INTERVALO_VARREDURA * 60)