import yfinance as yf
import requests

print("--- TESTE DE CONEXÃO: MODO DISFARCE (USER-AGENT) ---")

# 1. Criamos uma sessão de internet "falsa" que finge ser um Chrome no Windows
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

try:
    print("Tentando baixar PETR4.SA usando credenciais de navegador...")
    
    # 2. Passamos essa sessão para o yfinance
    # Isso faz o pedido sair com o carimbo do Chrome
    petro = yf.Ticker("PETR4.SA", session=session)
    historico = petro.history(period="5d")
    
    if not historico.empty:
        print(f"✅ SUCESSO! Conexão estabelecida.")
        print(f"Preço atual PETR4: R$ {historico['Close'].iloc[-1]:.2f}")
    else:
        print("❌ FALHA: Dados vieram vazios mesmo com disfarce.")

    print("\nTentando baixar Bitcoin...")
    btc = yf.Ticker("BTC-USD", session=session)
    hist_btc = btc.history(period="5d")
    
    if not hist_btc.empty:
        print(f"✅ SUCESSO! Bitcoin: U$ {hist_btc['Close'].iloc[-1]:.2f}")
    else:
        print("❌ FALHA: Bitcoin vazio.")

except TypeError as te:
    print(f"❌ ERRO DE VERSÃO: {te}")
    print("Parece que o yfinance 1.0 mudou como aceita a 'session'.")
except Exception as e:
    print(f"❌ ERRO CRÍTICO: {e}")

print("----------------------------------------------------")