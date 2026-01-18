import yfinance as yf

# Mostra a versão para garantir que o downgrade funcionou
print(f"--- TESTE FINAL (Versão: {yf.__version__}) ---")

try:
    # Teste com PETR4
    print("Baixando PETR4.SA...")
    petr = yf.Ticker("PETR4.SA")
    hist = petr.history(period="5d")
    
    if not hist.empty:
        print(f"✅ SUCESSO! Último preço: R$ {hist['Close'].iloc[-1]:.2f}")
    else:
        print("❌ VAZIO (O downgrade não resolveu).")

    # Teste com Bitcoin
    print("\nBaixando BTC-USD...")
    btc = yf.Ticker("BTC-USD")
    hist_btc = btc.history(period="5d")
    
    if not hist_btc.empty:
        print(f"✅ SUCESSO! Bitcoin: U$ {hist_btc['Close'].iloc[-1]:.2f}")
    else:
        print("❌ BTC VAZIO.")

except Exception as e:
    print(f"❌ ERRO: {e}")

print("----------------------------------------------")