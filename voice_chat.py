"""
見守りシステム - 音声対応チャットボット
========================================
STT（音声→テキスト）: Azure Speech Service
TTS（テキスト→音声）: Azure Speech Service
会話エンジン         : core_chatbot.py を使い回し

使い方：
  python voice_chat.py
  → マイクに向かって話すと、音声で返答してくれます
"""

import os
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
from core_chatbot import (
    chat, init_db, save_log, save_memory,
    load_recent_memory, summarize_conversation, get_weekly_stats
)

load_dotenv()

# =============================================
# Azure Speech 設定
# =============================================
SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY")
SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "japaneast")

def create_speech_config():
    """音声設定を作成"""
    config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SPEECH_REGION
    )
    # 日本語に設定
    config.speech_recognition_language = "ja-JP"
    config.speech_synthesis_language   = "ja-JP"
    # 音声の種類：穏やかな女性の声
    config.speech_synthesis_voice_name = "ja-JP-NanamiNeural"
    return config


# =============================================
# STT：音声 → テキスト
# =============================================
def listen() -> str:
    config = create_speech_config()
    # 無音タイムアウトを長めに設定
    config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
        "10000"   # 10秒待つ
    )
    config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
        "2000"    # 話し終わり判定を2秒に
    )
    recognizer = speechsdk.SpeechRecognizer(speech_config=config)

    print("🎤 聞いています... （話しかけてください）")
    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"認識：{result.text}")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        print("（聞き取れませんでした）")
        return ""
    else:
        print(f"エラー：{result.reason}")
        return ""


# =============================================
# TTS：テキスト → 音声
# =============================================
def speak(text: str):
    config      = create_speech_config()
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config)

    # 文章を句読点で分割して間を入れる
    text_with_pause = text.replace("。", "。<break time='400ms'/>") \
                          .replace("、", "、<break time='200ms'/>") \
                          .replace("？", "？<break time='300ms'/>") \
                          .replace("！", "！<break time='300ms'/>")

    ssml = f"""
    <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
           xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='ja-JP'>
      <voice name='ja-JP-NanamiNeural'>
        <mstts:express-as style='friendly' styledegree='2.0'>
          <prosody rate='0.85' pitch='+8%' volume='soft'>
            {text_with_pause}
          </prosody>
        </mstts:express-as>
      </voice>
    </speak>"""

    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"音声合成エラー：{result.reason}")


# =============================================
# メイン：音声会話ループ
# =============================================
def main():
    print("=" * 45)
    print("  🌸 見守りチャットボット（音声版）")
    print("  終了：「おわり」と話しかけてください")
    print("=" * 45)

    # DB初期化
    init_db()

    user_id    = "parent_mom"
    history    = []
    turn_count = 0

    # 長期記憶を読み込む
    memory = load_recent_memory(user_id, days=3)
    if memory:
        print(f"\n📝 直近の記憶を読み込みました：\n{memory}\n")

    # 最初の挨拶（音声で話しかける）
    greeting_result = chat(
        user_id=user_id,
        message="おはようございます",
        history=[],
        memory_summary=memory,
    )
    print(f"\nボット：{greeting_result['reply']}\n")
    speak(greeting_result["reply"])

    history.append({"role": "user",      "content": "おはようございます"})
    history.append({"role": "assistant", "content": greeting_result["reply"]})
    save_log(greeting_result, turn_count=1)
    turn_count = 1

    # 音声会話ループ
    while True:
        # 音声を聞く
        user_text = listen()

        if not user_text:
            speak("すみません、聞き取れませんでした。もう一度お話しください。")
            continue

        # 「おわり」で終了
        if "おわり" in user_text or "終わり" in user_text:
            speak("今日もお話できて嬉しかったです。またお話しましょうね。")
            break

        turn_count += 1

        # 会話処理
        result = chat(
            user_id=user_id,
            message=user_text,
            history=history,
            memory_summary=memory,
        )

        print(f"ボット：{result['reply']}")
        print(
            f"  └ 感情：{result['sentiment']:.2f} "
            f"| tokens：{result['input_tokens'] + result['output_tokens']}\n"
        )

        # 音声で返答
        speak(result["reply"])

        # 履歴更新（メモリ上のみ）
        history.append({"role": "user",      "content": user_text})
        history.append({"role": "assistant", "content": result["reply"]})

        # DBに数値のみ保存
        save_log(result, turn_count=turn_count)

    # 会話終了：要約を保存
    print("\n--- 会話終了。要約を生成しています... ---")
    summary = summarize_conversation(history)
    if summary:
        save_memory(user_id, summary)
        print(f"📝 保存した要約：\n{summary}")

    # 今週のスタッツ表示
    stats = get_weekly_stats(user_id)
    print(f"\n📊 今週の記録（{user_id}）：")
    for day in stats["days"]:
        sentiment_bar = "😊" if (day["avg_sentiment"] or 0) >= 0.6 else "😐" if (day["avg_sentiment"] or 0) >= 0.4 else "😔"
        print(
            f"  {day['date']} {sentiment_bar} "
            f"感情：{day['avg_sentiment']}  "
            f"tokens：{day['total_tokens']}  "
            f"ターン：{day['total_turns']}"
        )

    print("\n✅ 終了しました。")


if __name__ == "__main__":
    main()