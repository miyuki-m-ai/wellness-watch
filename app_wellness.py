"""
wellness monitoring app - voice version with password
STT: st_javascript を使ってJS→Pythonに音声認識結果を渡す
"""

import os
import streamlit as st
import streamlit.components.v1 as components
from streamlit_javascript import st_javascript
from dotenv import load_dotenv
from openai import AzureOpenAI
from core_chatbot import (
    init_db, save_log, save_memory,
    load_recent_memory, summarize_conversation,
    get_sentiment,
)
from datetime import datetime

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
# speak() - Web Speech API TTS版
# =============================================
def speak(text):
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
    escaped = (
        text
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    js = f"""
    <script>
    (function() {{
        if (!('speechSynthesis' in window)) return;
        window.speechSynthesis.cancel();
        const utter = new SpeechSynthesisUtterance(`{escaped}`);
        utter.lang   = 'ja-JP';
        utter.rate   = 0.85;
        utter.pitch  = 1.1;
        utter.volume = 0.9;
        const trySpeak = () => {{
            const voices = window.speechSynthesis.getVoices();
            const jaVoice = voices.find(v => v.lang === 'ja-JP' || v.lang.startsWith('ja'));
            if (jaVoice) utter.voice = jaVoice;
            window.speechSynthesis.speak(utter);
        }};
        if (window.speechSynthesis.getVoices().length > 0) {{
            trySpeak();
        }} else {{
            window.speechSynthesis.onvoiceschanged = trySpeak;
        }}
    }})();
    </script>
    """
    components.html(js, height=0)


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
        "reply"        : reply,
        "sentiment"    : sentiment,
        "input_tokens" : response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "timestamp"    : datetime.now().isoformat(),
        "user_id"      : USER_ID,
    }


def end_conversation():
    speak("今日もお話できて嬉しかったです。またお話しましょうね。")
    st.session_state.messages.append({"role": "bot", "text": "今日もお話できて嬉しかったです。またお話しましょうね。🌸"})
    summary = summarize_conversation(st.session_state.history)
    if summary:
        save_memory(USER_ID, summary)
    st.session_state.talking  = False
    st.session_state.finished = True


if "initialized" not in st.session_state:
    init_db()
    memory = load_recent_memory(USER_ID, days=3)
    st.session_state.memory      = memory
    st.session_state.history     = []
    st.session_state.messages    = []
    st.session_state.turn        = 0
    st.session_state.talking     = False
    st.session_state.finished    = False
    st.session_state.initialized = True

    greeting = chat_flexible("おはようございます", [], memory)
    st.session_state.history  += [
        {"role": "user",      "content": "おはようございます"},
        {"role": "assistant", "content": greeting["reply"]},
    ]
    st.session_state.messages.append({"role": "bot", "text": greeting["reply"]})
    save_log(greeting, turn_count=1)
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
# 音声認識
# =============================================
if not st.session_state.get("listening"):
    if st.button("🎤 はなしかける", key="mic_btn", use_container_width=True):
        st.session_state.listening    = True
        st.session_state.voice_result = None
        st.rerun()
else:
    st.info("🎤 きいています... はなしかけてください")
    voice_result = st_javascript("""
        await new Promise((resolve) => {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) { resolve("__unsupported__"); return; }
            const recognition = new SpeechRecognition();
            recognition.lang = 'ja-JP';
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;
            recognition.onresult = (e) => resolve(e.results[0][0].transcript);
            recognition.onerror  = (e) => resolve("__error__");
            recognition.start();
        });
    """)

    if voice_result is not None and isinstance(voice_result, str):
        st.session_state.listening = False
        user_text = voice_result.strip()

        if user_text in ("", "__unsupported__", "__error__"):
            st.warning("もう一度はなしかけてください")
            st.rerun()
        elif is_end_word(user_text):
            end_conversation()
            st.rerun()
        else:
            st.session_state.turn += 1
            result = chat_flexible(user_text, st.session_state.history, st.session_state.memory)
            st.session_state.history += [
                {"role": "user",      "content": user_text},
                {"role": "assistant", "content": result["reply"]},
            ]
            st.session_state.messages += [
                {"role": "user", "text": user_text},
                {"role": "bot",  "text": result["reply"]},
            ]
            save_log(result, turn_count=1)
            speak(result["reply"])
            st.rerun()

st.markdown('<div class="btn-end">', unsafe_allow_html=True)
end_btn = st.button("👋 おわる", key="end_btn", use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

if end_btn:
    end_conversation()
    st.rerun()
