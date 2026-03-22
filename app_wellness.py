"""
wellness monitoring app - voice version with password
"""

import os
import streamlit as st
import azure.cognitiveservices.speech as speechsdk
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

SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY")
SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "japaneast")
USER_ID       = os.getenv("USER_ID", "parent_mom")

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


def create_speech_config():
    config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    config.speech_recognition_language = "ja-JP"
    config.speech_synthesis_language   = "ja-JP"
    config.speech_synthesis_voice_name = "ja-JP-KeitaNeural"
    config.set_property(speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "8000")
    config.set_property(speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "1500")
    return config


def listen():
    config     = create_speech_config()
    recognizer = speechsdk.SpeechRecognizer(speech_config=config)
    result     = recognizer.recognize_once_async().get()
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        return result.text
    return ""


def speak(text):
    config      = create_speech_config()
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config)
    t = text.replace("。", "。<break time='400ms'/>").replace("、", "、<break time='200ms'/>")
    ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
        xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='ja-JP'>
      <voice name='ja-JP-KeitaNeural'>
        <mstts:express-as style='friendly' styledegree='2.0'>
          <prosody rate='0.85' pitch='+5%' volume='soft'>{t}</prosody>
        </mstts:express-as>
      </voice>
    </speak>"""
    synthesizer.speak_ssml_async(ssml).get()


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

col1, col2 = st.columns([3, 2])

with col1:
    st.markdown('<div class="btn-talk">', unsafe_allow_html=True)
    talk_btn = st.button(
        "🎤 きいています..." if st.session_state.talking else "🎤 はなしかける",
        key="talk_btn", use_container_width=True,
        disabled=st.session_state.talking
    )
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="btn-end">', unsafe_allow_html=True)
    end_btn = st.button("👋 おわる", key="end_btn", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

if end_btn:
    end_conversation()
    st.rerun()

if talk_btn:
    st.session_state.talking = True
    st.rerun()

if st.session_state.talking:
    st.markdown('<div class="status-talking">🎤 きいています...「バイバイ」でおわります</div>', unsafe_allow_html=True)
    user_text = listen()

    if not user_text:
        speak("もう一度おはなしください。")
        st.rerun()
    elif is_end_word(user_text):
        end_conversation()
        st.rerun()
    else:
        st.session_state.turn += 1
        result = chat_flexible(user_text, st.session_state.history, st.session_state.memory)
        st.session_state.history += [{"role":"user","content":user_text},{"role":"assistant","content":result["reply"]}]
        st.session_state.messages += [{"role":"user","text":user_text},{"role":"bot","text":result["reply"]}]
        save_log_direct(result, st.session_state.turn)
        speak(result["reply"])
        st.rerun()