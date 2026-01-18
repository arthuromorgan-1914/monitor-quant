import shutil
import os
import requests
import yfinance as yf
from pathlib import Path

print("--- INICIANDO PROTOCOLO DE RESET ---")

# 1. FAXINA DO CACHE (O Exorcismo)
# O yfinance guarda lixo em AppData/Local/py-yfinance
cache_path = Path(os.getenv('LOCALAPPDATA')) / "py-yfinance"

if cache_path.exists():
    try:
        shutil.rmtree(cache_path)
        print(f"✅ Cache deletado em: {cache_path}")
        print("   (A memória do bloqueio foi apagada)")
    except Exception as e:
        print(f"⚠️ Não consegui apagar o cache: {e}")
else:
    print("✅ Nenhum cache antigo encontrado.")

# 2. O DISFARCE (Fingindo ser Chrome)
# Como voltamos para a v0.2.54, isso VOLTA a funcionar!
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

print("\n--- TESTANDO CONEXÃO COM DISFARCE ---")
try:
    # Passamos a 'session' disfarçada para o Ticker
    petr = yf.Ticker("PETR4.SA", session=session)
    
    # Tentamos baixar
    dados = petr.history(period="5d")
    
    if not dados.empty:
        print(f"🚀 SUCESSO TOTAL! O bloqueio foi vencido.")
        print(f"   Preço PETR4: R$ {dados['Close'].iloc[-1]:.2f}")
    else:
        print("❌ Ainda veio vazio... O bloqueio de IP no 4G persiste?")

except Exception as e:
    print(f"❌ ERRO: {e}")

print("------------------------------------")