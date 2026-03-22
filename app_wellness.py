"""
wellness monitoring app - voice version with password
speak() → Web Speech API (ブラウザ音声合成) に変更
listen() は今後対応予定
"""

import os
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import AzureOpenAI
from core_chatbot import (
    init_db, save_memory,
    load_recent_memory, summarize_conversation,
    get_sentiment, DB_PATH
)
from datetime import datetime, date
import sqlite3

load_dotenv()

USER_ID = os.getenv("USER_ID", "parent_mom")

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01",
)
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

st.set_page_config(page_title="おはなししよう", page_icon="🌸", layout="centered")

st.markdown("""
<style>
  #MainMenu {visibility: hidden;}
  header {visibility: hidden;}
  html, body, [class*="css"] {
    font-size: 20px !important;
    font-family: 'Hiragino Sans', 'Meiryo', sans-serif;
  }
  .title { text-align:center; font-size:2.5rem; color:#e75480; margin-bottom:5px; font-weight:bold; }
  .subtitle { text-align:center; font-size:1.2rem; color:#888; margin-bottom:10px; }
  .bubble-bot {
    background:#fff0f5; border-left:5px solid #e75480; border-radius:15px;
    padding:16px 20px; margin:10px 0; font-size:1.3rem; line-height:1.8; color:#333;
  }
  .bubble-user {
    background:#f0f8ff; border-left:5px solid #4a90d9; border-radius:15px;
    padding:16px 20px; margin:10px 0; font-size:1.3rem; line-height:1.8; color:#333; text-align:right;
  }
  .status-talking {
    text-align:center; font-size:1.4rem; padding:15px; border-radius:15px;
    margin:10px 0; background:#ffe0f0; color:#c0155a;
  }
  .btn-talk > button {
    width:100% !important; height:110px !important; font-size:1.8rem !important;
    border-radius:20px !important;
    background:linear-gradient(135deg,#ff8fab,#e75480) !important;
    color:white !important; font-weight:bold !important;
    box-shadow:0 6px 20px rgba(231,84,128,0.4) !important;
  }
  .btn-end > button {
    width:100% !important; height:80px !important; font-size:1.4rem !important;
    border-radius:20px !important;
    background:linear-gradient(135deg,#adb5bd,#6c757d) !important;
    color:white !important; box-shadow:none !important;
  }
  .btn-login > button {
    width:100% !important; height:90px !important; font-size:1.8rem !important;
    border-radius:20px !important;
    background:linear-gradient(135deg,#ff8fab,#e75480) !important;
    color:white !important; font-weight:bold !important;
  }
  .login-input > div > input {
    font-size:1.5rem !important; height:60px !important;
    text-align:center !important; border-radius:15px !important;
  }
</style>
""", unsafe_allow_html=True)


# =============================================
# パスワード認証
# =============================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown('<div class="title">🌸 おはなししよう</div>', unsafe_allow_html=True)
    st.divider()
    st.markdown('<div class="subtitle">パスワードをいれてください</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-input">', unsafe_allow_html=True)
    password = st.text_input("", type="password", key="pw_input", label_visibility="collapsed")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="btn-login">', unsafe_allow_html=True)
    if st.button("はいる", key="login_btn", use_container_width=True):
        if password == os.getenv("APP_PASSWORD", "hana1234"):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("パスワードがちがいます")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()


# =============================================
# speak() - Web Speech API版（Azure Speech SDK不要）
# =============================================
def speak(text):
    """ブラウザのWeb Speech APIで音声合成する"""
    # --- 誤読み修正（表示テキストは変えず、読み上げ用に置換）---
    text = text.replace("今日", "きょう")
    text = text.replace("明日", "あした")
    text = text.replace("昨日", "きのう")
    text = text.replace("今夜", "こんや")
    text = text.replace("今朝", "けさ")
    text = text.replace("今週", "こんしゅう")
    text = text.replace("来週", "らいしゅう")
    text = text.replace("先週", "せんしゅう")
    text = text.replace("今月", "こんげつ")
    text = text.replace("来月", "らいげつ")
    text = text.replace("今年", "ことし")
    text = text.replace("来年", "らいねん")
    text = text.replace("元気", "げんき")
    text = text.replace("大丈夫", "だいじょうぶ")
    text = text.replace("一緒", "いっしょ")
    text = text.replace("嬉しい", "うれしい")
    text = text.replace("嬉しかった", "うれしかった")
    # ----------------------------------------------------------
    # バッククォート・バックスラッシュ・$をエスケープしてJSテンプレートリテラルに安全に埋め込む
    escaped = (
        text
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    js = f"""
    <script>
    (function() {{
        if (!('speechSynthesis' in window)) {{
            console.warn('Web Speech API not supported');
            return;
        }}
        window.speechSynthesis.cancel();

        const utter = new SpeechSynthesisUtterance(`{escaped}`);
        utter.lang    = 'ja-JP';
        utter.rate    = 0.85;   // ゆっくり話す（高齢者向け）
        utter.pitch   = 1.1;
        utter.volume  = 0.9;

        const trySpeak = () => {{
            const voices = window.speechSynthesis.getVoices();
            // ja-JP の音声を優先選択（なければデフォルト）
            const jaVoice = voices.find(v => v.lang === 'ja-JP' || v.lang.startsWith('ja'));
            if (jaVoice) utter.voice = jaVoice;
            window.speechSynthesis.speak(utter);
        }};

        // getVoices() は非同期で読み込まれる場合があるため両方対応
        if (window.speechSynthesis.getVoices().length > 0) {{
            trySpeak();
        }} else {{
            window.speechSynthesis.onvoiceschanged = trySpeak;
        }}
    }})();
    </script>
    """
    # height=0 で非表示のiframeとして注入
    components.html(js, height=0)


# =============================================
# listen() - 現状はテキスト入力で代替
# ※ Web Speech API (STT) 版は今後実装予定
# =============================================
def listen():
    """
    暫定：st.text_inputでテキスト入力を受け付ける。
    Web Speech API (STT) 版への置き換えは次のステップで対応。
    """
    return st.session_state.get("user_input_text", "")


def is_end_word(text):
    end_words = ["バイバイ", "ばいばい", "おわり", "終わり", "さようなら",
                 "おしまい", "やめる", "終了", "またね", "またねー"]
    return any(word in text for word in end_words)


def build_system_prompt(memory_summary=""):
    base = (
        "You are a warm and friendly conversation partner for an elderly Japanese person.\n"
        "Always respond in Japanese.\n"
        "Her name is Junko. Call her 'junkochan' occasionally to make her feel welcome.\n"
        "You can help with daily conversation, health concerns, questions about weather or news,\n"
        "and any other topics she wants to discuss.\n"
        "Keep responses short (2-3 sentences). Ask only one question at a time.\n"
        "Use simple, gentle language."
    )
    if memory_summary:
        base += "\n\nRecent information about her:\n" + memory_summary
    return base


def chat_flexible(message, history, memory_summary=""):
    messages = [{"role": "system", "content": build_system_prompt(memory_summary)}]
    messages += history
    messages += [{"role": "user", "content": message}]
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME, messages=messages, max_tokens=512, temperature=0.8
    )
    reply = response.choices[0].message.content
    sentiment = get_sentiment(message)
    return {
        "reply": reply, "sentiment": sentiment,
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "timestamp": datetime.now().isoformat(), "user_id": USER_ID,
    }


def save_log_direct(log, turn_count=1):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, date TEXT, timestamp TEXT,
        sentiment REAL, input_tokens INTEGER, output_tokens INTEGER, turn_count INTEGER DEFAULT 1
    )""")
    conn.execute(
        "INSERT INTO daily_log (user_id,date,timestamp,sentiment,input_tokens,output_tokens,turn_count) VALUES (?,?,?,?,?,?,?)",
        (log["user_id"], date.today().isoformat(), log["timestamp"],
         log["sentiment"], log["input_tokens"], log["output_tokens"], turn_count)
    )
    conn.commit()
    conn.close()


def end_conversation():
    speak("今日もお話できて嬉しかったです。またお話しましょうね。")
    st.session_state.messages.append({"role":"bot","text":"今日もお話できて嬉しかったです。またお話しましょうね。🌸"})
    summary = summarize_conversation(st.session_state.history)
    if summary:
        save_memory(USER_ID, summary)
    st.session_state.talking  = False
    st.session_state.finished = True


if "initialized" not in st.session_state:
    init_db()
    memory = load_recent_memory(USER_ID, days=3)
    st.session_state.memory   = memory
    st.session_state.history  = []
    st.session_state.messages = []
    st.session_state.turn     = 0
    st.session_state.talking  = False
    st.session_state.finished = False
    st.session_state.initialized = True

    greeting = chat_flexible("おはようございます", [], memory)
    st.session_state.history  += [{"role":"user","content":"おはようございます"},{"role":"assistant","content":greeting["reply"]}]
    st.session_state.messages.append({"role":"bot","text":greeting["reply"]})
    save_log_direct(greeting, 1)
    speak(greeting["reply"])


# =============================================
# UI描画
# =============================================
st.markdown('<div class="title">🌸 おはなししよう</div>', unsafe_allow_html=True)

if st.session_state.finished:
    st.markdown('<div class="subtitle">またおはなししましょうね 🌸</div>', unsafe_allow_html=True)
    st.stop()

st.divider()

for msg in st.session_state.messages[-6:]:
    if msg["role"] == "bot":
        st.markdown(f'<div class="bubble-bot">🌸 {msg["text"]}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="bubble-user">{msg["text"]} 🗣️</div>', unsafe_allow_html=True)

st.divider()

# =============================================
# テキスト入力UI（listen()の暫定代替）
# =============================================
user_input = st.text_input(
    "メッセージをいれてください",
    key="user_input_text",
    label_visibility="visible",
    placeholder="ここにことばをいれてください…"
)

col1, col2 = st.columns([3, 2])

with col1:
    st.markdown('<div class="btn-talk">', unsafe_allow_html=True)
    talk_btn = st.button(
        "💬 おくる",
        key="talk_btn", use_container_width=True,
        disabled=st.session_state.talking or not user_input
    )
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="btn-end">', unsafe_allow_html=True)
    end_btn = st.button("👋 おわる", key="end_btn", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

if end_btn:
    end_conversation()
    st.rerun()

if talk_btn and user_input:
    if is_end_word(user_input):
        end_conversation()
        st.rerun()
    else:
        st.session_state.talking = True
        st.session_state.turn += 1
        result = chat_flexible(user_input, st.session_state.history, st.session_state.memory)
        st.session_state.history += [{"role":"user","content":user_input},{"role":"assistant","content":result["reply"]}]
        st.session_state.messages += [{"role":"user","text":user_input},{"role":"bot","text":result["reply"]}]
        save_log_direct(result, st.session_state.turn)
        speak(result["reply"])
        st.session_state.talking = False
        st.rerun()