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

import html
import os
import time

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

from core_chatbot import (
    chat,
    get_weekly_stats,
    init_db,
    load_recent_memory,
    save_log,
    save_memory,
    summarize_conversation,
)

load_dotenv()

# =============================================
# 定数
# =============================================
SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY")
SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "japaneast")

# 終了ワード（完全一致 or 前後スペース除去で判定）
STOP_WORDS = {"おわり", "終わり", "終了", "バイバイ", "さようなら"}

# STT：無音タイムアウト設定
INITIAL_SILENCE_TIMEOUT_MS = "10000"   # 話し始めを10秒待つ
END_SILENCE_TIMEOUT_MS     = "2000"    # 話し終わり判定を2秒に

# リトライ設定
MAX_LISTEN_RETRIES = 3


# =============================================
# 起動時チェック
# =============================================
def check_env():
    """必須の環境変数が揃っているか確認する"""
    if not SPEECH_KEY:
        raise EnvironmentError(
            "AZURE_SPEECH_KEY が .env に設定されていません。"
            ".env ファイルを確認してください。"
        )
    if not SPEECH_REGION:
        raise EnvironmentError(
            "AZURE_SPEECH_REGION が .env に設定されていません。"
        )


# =============================================
# Azure Speech 設定（シングルトン）
# =============================================
_speech_config: speechsdk.SpeechConfig | None = None


def get_speech_config() -> speechsdk.SpeechConfig:
    """SpeechConfig をシングルトンで返す（毎回生成しない）"""
    global _speech_config
    if _speech_config is None:
        config = speechsdk.SpeechConfig(
            subscription=SPEECH_KEY,
            region=SPEECH_REGION,
        )
        config.speech_recognition_language = "ja-JP"
        config.speech_synthesis_language   = "ja-JP"
        config.speech_synthesis_voice_name = "ja-JP-NanamiNeural"
        config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
            INITIAL_SILENCE_TIMEOUT_MS,
        )
        config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
            END_SILENCE_TIMEOUT_MS,
        )
        _speech_config = config
    return _speech_config


# =============================================
# STT：音声 → テキスト
# =============================================
def listen() -> str:
    """
    マイクから音声を1回認識してテキストを返す。
    認識できなかった場合は空文字を返す。
    ネットワークエラーなど重大な失敗は例外を再送出する。
    """
    recognizer = speechsdk.SpeechRecognizer(speech_config=get_speech_config())

    print("🎤 聞いています... （話しかけてください）")
    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        text = result.text.strip()
        print(f"認識：{text}")
        return text

    if result.reason == speechsdk.ResultReason.NoMatch:
        no_match_detail = result.no_match_details
        print(f"（聞き取れませんでした：{no_match_detail.reason}）")
        return ""

    if result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.CancellationDetails.from_result(result)
        print(f"⚠️ 音声認識がキャンセルされました")
        print(f"   理由  ：{details.reason}")
        print(f"   詳細  ：{details.error_details}")
        # 認証エラーは続行不可なので例外を上げる
        if details.reason == speechsdk.CancellationReason.Error:
            raise RuntimeError(
                f"Azure Speech 認証エラー：{details.error_details}\n"
                "AZURE_SPEECH_KEY / AZURE_SPEECH_REGION を確認してください。"
            )
        return ""

    print(f"（予期しない結果：{result.reason}）")
    return ""


def listen_with_retry(max_retries: int = MAX_LISTEN_RETRIES) -> str:
    """
    listen() を最大 max_retries 回試みる。
    空文字が続いた場合はユーザーに声かけして再試行する。
    """
    for attempt in range(1, max_retries + 1):
        text = listen()
        if text:
            return text
        if attempt < max_retries:
            speak("すみません、聞き取れませんでした。もう一度お話しください。")
    # max_retries 回すべて空だった
    return ""


# =============================================
# TTS：テキスト → 音声
# =============================================
def speak(text: str) -> bool:
    """
    テキストを音声合成して再生する。
    成功した場合は True、失敗した場合は False を返す。
    失敗時はテキストをコンソールに出力してフォールバックする。
    """
    # SSML 内に埋め込む前に HTML エスケープ（< > & などを安全化）
    safe_text = html.escape(text)

    # 句読点に間（ポーズ）を追加
    text_with_pause = (
        safe_text
        .replace("。", "。<break time='400ms'/>")
        .replace("、", "、<break time='200ms'/>")
        .replace("？", "？<break time='300ms'/>")
        .replace("！", "！<break time='300ms'/>")
    )

    ssml = f"""
    <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
           xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='ja-JP'>
      <voice name='ja-JP-NanamiNeural'>
        <mstts:express-as style='friendly' styledegree='2.0'>
          <prosody rate='1.2' pitch='+8%' volume='soft'>
            {text_with_pause}
          </prosody>
        </mstts:express-as>
      </voice>
    </speak>"""

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=get_speech_config())
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return True

    # 失敗：詳細を出力してテキストでフォールバック
    if result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.CancellationDetails.from_result(result)
        print(f"⚠️ 音声合成エラー：{details.reason} / {details.error_details}")
    else:
        print(f"⚠️ 音声合成エラー：{result.reason}")

    print(f"📢 （テキスト出力）: {text}")
    return False


# =============================================
# ユーティリティ
# =============================================
def is_stop_word(text: str) -> bool:
    """終了ワードかどうかを判定する（完全一致）"""
    return text.strip() in STOP_WORDS


def print_separator(char: str = "-", width: int = 45):
    print(char * width)


# =============================================
# メイン：音声会話ループ
# =============================================
def main():
    # 起動時に環境変数チェック
    try:
        check_env()
    except EnvironmentError as e:
        print(f"❌ 設定エラー：{e}")
        return

    print("=" * 45)
    print("  🌸 見守りチャットボット（音声版）")
    print("  終了：「おわり」と話しかけてください")
    print("=" * 45)

    # DB 初期化
    init_db()

    user_id    = "parent_mom"
    history: list[dict] = []
    turn_count = 0

    # 長期記憶を読み込む
    memory = load_recent_memory(user_id, days=3)
    if memory:
        print(f"\n📝 直近の記憶を読み込みました：\n{memory}\n")

    # 最初の挨拶
    try:
        greeting_result = chat(
            user_id=user_id,
            message="おはようございます",
            history=[],
            memory_summary=memory,
        )
    except Exception as e:
        print(f"❌ 挨拶の生成に失敗しました：{e}")
        return

    print(f"\nボット：{greeting_result['reply']}\n")
    speak(greeting_result["reply"])

    history.append({"role": "user",      "content": "おはようございます"})
    history.append({"role": "assistant", "content": greeting_result["reply"]})
    save_log(greeting_result, turn_count=1)
    turn_count = 1

    # 音声会話ループ
    while True:
        # 音声を聞く（リトライあり）
        try:
            user_text = listen_with_retry()
        except RuntimeError as e:
            # 認証エラーなど回復不能なエラー
            print(f"❌ 致命的エラーが発生しました：{e}")
            break

        if not user_text:
            # MAX_LISTEN_RETRIES 回すべて聞き取れなかった
            speak("少し休憩しますね。また話しかけてください。")
            time.sleep(3)
            continue

        # 終了ワード判定
        if is_stop_word(user_text):
            speak("今日もお話できて嬉しかったです。またお話しましょうね。")
            break

        turn_count += 1

        # 会話処理
        try:
            result = chat(
                user_id=user_id,
                message=user_text,
                history=history,
                memory_summary=memory,
            )
        except Exception as e:
            print(f"⚠️ 返答の生成に失敗しました：{e}")
            speak("少し考えすぎてしまいました。もう一度お話しください。")
            continue

        print(f"ボット：{result['reply']}")
        print(
            f"  └ 感情：{result['sentiment']:.2f} "
            f"| tokens：{result['input_tokens'] + result['output_tokens']}\n"
        )

        # 音声で返答
        speak(result["reply"])

        # 履歴更新
        history.append({"role": "user",      "content": user_text})
        history.append({"role": "assistant", "content": result["reply"]})

        # DB に保存
        save_log(result, turn_count=turn_count)

    # =============================================
    # 会話終了処理
    # =============================================
    print_separator()
    print("会話終了。要約を生成しています...")
    print_separator()

    try:
        summary = summarize_conversation(history)
        if summary:
            save_memory(user_id, summary)
            print(f"📝 保存した要約：\n{summary}")
    except Exception as e:
        print(f"⚠️ 要約の保存に失敗しました：{e}")

    # 今週のスタッツ表示
    try:
        stats = get_weekly_stats(user_id)
        print(f"\n📊 今週の記録（{user_id}）：")
        for day in stats["days"]:
            avg = day["avg_sentiment"] or 0
            sentiment_bar = "😊" if avg >= 0.6 else "😐" if avg >= 0.4 else "😔"
            print(
                f"  {day['date']} {sentiment_bar} "
                f"感情：{day['avg_sentiment']}  "
                f"tokens：{day['total_tokens']}  "
                f"ターン：{day['total_turns']}"
            )
    except Exception as e:
        print(f"⚠️ 週次統計の表示に失敗しました：{e}")

    print("\n✅ 終了しました。")


if __name__ == "__main__":
    main()