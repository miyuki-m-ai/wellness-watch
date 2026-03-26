@echo off
echo === 見守りシステム 起動中 ===

cd /d C:\Users\bhgwp\OneDrive\RAG_Knowledge\wellness-watch

:: 仮想環境を有効化してline_bot.pyを起動
start "LINE Bot" cmd /k "C:\Users\bhgwp\OneDrive\RAG_Knowledge\wellness-watch\.venv\Scripts\activate.bat && python line_bot.py"

:: 少し待つ
timeout /t 3 /nobreak

:: ngrokを固定ドメインで起動
start "ngrok" cmd /k "ngrok http --url https://unencountered-apsidally-werner.ngrok-free.dev 5000"

:: 少し待つ
timeout /t 3 /nobreak

:: schedulerを起動
start "Scheduler" cmd /k "C:\Users\bhgwp\OneDrive\RAG_Knowledge\wellness-watch\.venv\Scripts\activate.bat && python scheduler.py"
:: ダッシュボードを起動
start "Dashboard" cmd /k "C:\Users\bhgwp\OneDrive\RAG_Knowledge\wellness-watch\.venv\Scripts\activate.bat && streamlit run app_dashboard.py --server.port 8502"

echo === 起動完了 ===