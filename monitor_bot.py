import shutil
import os
import requests
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import random
from datetime import datetime
from pathlib import Path

# ==============================================================================
# CONFIGURAÇÕES PESSOAIS (ATENÇÃO REDOBRADA AQUI)
# ==============================================================================
# Dica: O Token geralmente começa com números, ex: "7182...:AAF..."
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"      
CHAT_ID = "1116977306"  

CARTEIRA = [
    "BTC-USD", "ETH-USD", "SOL-USD", 
    "PETR4.SA", "VALE3.SA", "WEGE3.SA", "PRIO3.SA",
    "AAPL", "NVDA", "MSFT", "TSLA"
]

INTERVALO_VARREDURA = 60 # Minutos
# ==============================================================================

def limpar_cache_yahoo():
    """Função faxineira: Apaga a memória do bloqueio antes de começar"""
    try:
        cache_path = Path(os.getenv('LOCALAPPDATA')) / "py-yfinance"
        if cache_path.exists():
            shutil.rmtree(cache_path)
            print("🧹 Cache antigo deletado (Rastros apagados).")
    except Exception:
        pass # Se der erro na limpeza, segue o jogo

def criar_sessao_disfarce():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def enviar_telegram(mensagem):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID, 
            "text": mensagem, 
            "disable_web_page_preview": True
        }
        resp = requests.post(url, data=data)
        
        if resp.status_code != 200:
            # Se der 404 aqui, o TOKEN está errado.
            print(f"❌ ERRO TELEGRAM (Cód {resp.status_code}): {resp.text}")
            print("⚠️ DICA: Verifique se colou o TOKEN corretamente.")
        else:
            print(">> Mensagem enviada ao Telegram!")
            
    except Exception as e:
        print(f"❌ Erro de Conexão Telegram: {e}")

def analisar_mercado():
    # 1. Limpa o cache ANTES de tudo
    limpar_cache_yahoo()
    
    hora_atual = datetime.now().strftime('%H:%M')
    print(f"\n--- Iniciando Varredura ({hora_atual}) ---")
    
    sessao_fake = criar_sessao_disfarce()
    msg_relatorio = f"🔍 Monitor v4.0 ({hora_atual})\n\n"
    oportunidades = 0
    analisados = 0

    for ativo in CARTEIRA:
        try:
            # Tenta baixar
            ticker = yf.Ticker(ativo, session=sessao_fake)
            df = ticker.history(period="6mo")

            if df.empty:
                # Se falhar, tenta sem sessão (às vezes funciona melhor pra BR)
                ticker = yf.Ticker(ativo)
                df = ticker.history(period="6mo")

            if df.empty or len(df) < 22: 
                print(f"⚠️ {ativo}: Sem dados (Yahoo instável).")
                continue
            
            analisados += 1
            
            # Médias
            media_curta = ta.sma(df['Close'], length=9).iloc[-1]
            media_longa = ta.sma(df['Close'], length=21).iloc[-1]
            preco_atual = df['Close'].iloc[-1]
            
            if media_curta > media_longa:
                oportunidades += 1
                var_dia = ((preco_atual - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
                msg_relatorio += f"🟢 {ativo} | {preco_atual:.2f} ({var_dia:+.1f}%)\n"
                print(f"✅ {ativo}: ALTA")
            else:
                print(f"Checking {ativo}... OK")
                
            # Espera maior para evitar bloqueio
            time.sleep(random.randint(5, 10)) 

        except Exception as e:
            print(f"❌ Erro em {ativo}: {e}")
            time.sleep(5) # Espera extra se der erro

    # Envio
    if oportunidades > 0:
        msg_relatorio += "\n🚀 Verifique o Gráfico!"
        enviar_telegram(msg_relatorio)
    else:
        if analisados > 0:
            enviar_telegram(f"📉 Status ({hora_atual}): Mercado calmo.")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    print("✅ Robô Iniciado (v4.0 - Auto-Limpeza)!")
    enviar_telegram("🤖 Sistema Online\nSe você recebeu isso, o Token está certo.")

    while True:
        analisar_mercado()
        print(f"Dormindo por {INTERVALO_VARREDURA} minutos...")
        time.sleep(INTERVALO_VARREDURA * 60)