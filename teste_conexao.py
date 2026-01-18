import yfinance as yf

print("--- TESTE DE CONEXÃO COM YAHOO FINANCE ---")

try:
    # Tentativa 1: Método Cirúrgico (O que vamos usar no robô)
    print("Tentando baixar PETR4.SA...")
    petro = yf.Ticker("PETR4.SA")
    historico = petro.history(period="5d")
    
    if not historico.empty:
        print(f"✅ SUCESSO! Preço atual: R$ {historico['Close'].iloc[-1]:.2f}")
    else:
        print("❌ FALHA: Dados vieram vazios.")

    print("\nTentando baixar Bitcoin...")
    btc = yf.Ticker("BTC-USD")
    hist_btc = btc.history(period="5d")
    
    if not hist_btc.empty:
        print(f"✅ SUCESSO! Bitcoin: U$ {hist_btc['Close'].iloc[-1]:.2f}")
    else:
        print("❌ FALHA: Bitcoin veio vazio.")

except Exception as e:
    print(f"❌ ERRO CRÍTICO: {e}")

print("------------------------------------------")