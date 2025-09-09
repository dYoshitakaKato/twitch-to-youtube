# main.py
import os, requests, json
import datetime
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from openai import OpenAI
import re

# 環境変数で取得（GitHubで設定）
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_USER_ID = os.getenv("TWITCH_USER_ID")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # コスパ良
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PLAY_LIST_ID = os.getenv("PLAY_LIST_ID", "")

# YouTube認証
with open("token.json", "w", encoding="utf-8") as f:
    GOOGLE_TOKEN = os.getenv("GOOGLE_TOKEN")
    json.dump(json.loads(GOOGLE_TOKEN), f, ensure_ascii=False, indent=2)
creds = Credentials.from_authorized_user_file("token.json")
if creds.expired:
    creds.refresh(Request())
youtube = build("youtube", "v3", credentials=creds)

import update_previous_video_in_playlist

def execute():
    print("📤 Twitchビデオ取得")
    # アクセストークン取得
    auth = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    ).json()
    access_token = auth["access_token"]
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {access_token}"}
    r = requests.get(
        f"https://api.twitch.tv/helix/videos?user_id={TWITCH_USER_ID}&type=archive",
        headers=headers,
    )
    for vod in r.json().get("data", []):
        print("📤 Twitchビデオあり")
        created = datetime.datetime.strptime(vod["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        created = created.replace(tzinfo=datetime.timezone.utc)
        delta = datetime.datetime.now(datetime.timezone.utc) - created
        # 24時間以降48時間以内のアーカイブを取得
        if delta > datetime.timedelta(hours=24) and delta < datetime.timedelta(
            hours=48
        ):
            vod_url = vod["url"]
            title_ja = vod["title"]
            description = vod["description"]
            jst = created.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            if vod_url:
                filename = download_vod(vod_url)
                thumbnail_path = download_twitch_thumbnail(vod["thumbnail_url"])
                description_ja = create_description(jst, description)
                localizations = create_localizations(title_ja, description_ja)
                video_id = upload_to_youtube(filename, localizations, thumbnail_path)
                playlist_id = extract_playlist_id(localizations["ja"]["description"])
                add_video_to_playlist(video_id, list(playlist_id, PLAY_LIST_ID))
                update_previous_video_in_playlist.main(playlist_id, video_id)
    print("📤 Twitchビデオなし")
    return None, None


def create_description(jst, description):
    last_description_text = os.getenv("LAST_DESCRIPTION_TEXT", "")
    created_at = jst.strftime("%Y/%m/%d %H:%M")
    description_ja = (
        f"{created_at}(JST) Twitch配信のアーカイブ\n"
        f"{description}\n\n"
        f"{last_description_text}"
    )
    return description_ja


def download_vod(vod_url):
    print("📤 Twitchダウンロード開始")
    # Twitchの外部サービスで.m3u8からダウンロード or `streamlink`
    filename = "vod.mp4"
    start = time.time()
    os.system(f"streamlink --loglevel error {vod_url} best -f -o {filename}")
    end = time.time()  # 終了時刻
    print(f"Twitchダウンロード処理時間: {end - start:.2f} 秒")
    return filename


def download_twitch_thumbnail(thumbnail_url, output_path="thumbnail.jpg"):
    url = thumbnail_url.replace("%{width}", "1280").replace("%{height}", "720")
    response = requests.get(url)
    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
        return output_path
    else:
        raise Exception("サムネイルの取得に失敗しました")


def get_publish_at() -> str:
    hour = int(os.getenv("PUBLISH_HOUR_JST"))
    minute = int(os.getenv("PUBLISH_MINUTE_JST"))
    jst_timezone = datetime.timezone(datetime.timedelta(hours=9))
    now_jst = datetime.datetime.now(datetime.timezone.utc).astimezone(jst_timezone)
    target_jst = datetime.datetime(
        year=now_jst.year,
        month=now_jst.month,
        day=now_jst.day,
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
        tzinfo=jst_timezone,
    ) + datetime.timedelta(days=1)
    return to_rfc3339_utc(target_jst)


def to_rfc3339_utc(dt: datetime.datetime) -> str:
    # dt: timezone-aware（JSTなど）前提
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upload_to_youtube(file_path, localizations, thumbnail_path) -> str:
    print("📤 YouTubeにアップロード開始")
    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        chunksize=1024 * 1024 * 8,  # 8MBごとに分割
        resumable=True,
    )
    request = youtube.videos().insert(
        part="snippet,status,localizations",
        body={
            "snippet": {
                "defaultLanguage": "ja",
                "defaultAudioLanguage": "ja",
                "title": localizations["ja"]["title"],
                "description": localizations["ja"]["description"],
                "tags": os.getenv("YOUTUBE_TAGS").split(","),
                "categoryId": "20",  # Gaming
            },
            "status": {"privacyStatus": "private", "publishAt": get_publish_at()},
            "localizations": localizations,
        },
        media_body=media,
    )
    response = None
    start = time.time()
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%.")
    print("Upload Complete!")
    end = time.time()  # 終了時刻
    video_id = response["id"]
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
    ).execute()
    print(f"youtubeアップロード処理時間: {end - start:.2f} 秒")
    return video_id


def create_localizations(title_ja, description_ja) -> dict:
    try:
        title_en = translate_with_openai(title_ja, 100, "en")
        description_en = translate_with_openai(description_ja, 5000, "en")
        return {
            "ja": {"title": title_ja, "description": description_ja},
            "en": {"title": title_en, "description": description_en},
        }
    except Exception as e:
        print(f"[warn] translation failed: {e}")
        return {"ja": {"title": title_ja, "description": description_ja}}


def translate_with_openai(
    text: str, max_character_size: int, target_lang: str = "en"
) -> str:
    """
    ChatGPTで翻訳。改行・絵文字・記号を保持し、意訳しすぎないようにしてください。
    出力は翻訳テキストのみにしてください。
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=OPENAI_API_KEY)
    system = (
        "You are a professional translator. "
        "Translate the user's text. Keep line breaks, emojis, and punctuation. "
        "Do not add explanations. Output only the translated text. "
        f"The translated text must not exceed {max_character_size} characters."
    )
    user = f"Target language: {target_lang}\n\nTEXT:\n{text}"
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def extract_playlist_id(text: str) -> str | None:
    """
    文章中のYouTube再生リストURLからplaylistのIDを抽出する
    """
    # 正規表現でlist=以降のIDを取得
    match = re.search(r"list=([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1)
    return None


def add_video_to_playlist(video_id, playlist_ids):
    for playlist_id in playlist_ids:
        if not playlist_id:
            continue
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()
    print("動画を再生リストに追加しました。")


def main():
    print("🚀 main.py 実行開始")
    execute()
    print("🚀 main.py 実行終了")


if __name__ == "__main__":
    main()
