# main.py
import os, requests, json
import datetime
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# 環境変数で取得（GitHubで設定）
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_USER_ID = os.getenv("TWITCH_USER_ID")

# YouTube認証
with open("token.json", "w", encoding="utf-8") as f:
    GOOGLE_TOKEN = os.getenv("GOOGLE_TOKEN")
    json.dump(json.loads(GOOGLE_TOKEN), f, ensure_ascii=False, indent=2)
creds = Credentials.from_authorized_user_file("token.json")
if creds.expired:
    creds.refresh(Request())


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
            title = vod["title"]
            description = vod["description"]
            user_login = vod["user_login"]
            jst = created.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            channel_url = f"https://www.twitch.tv/{user_login}"
            if vod_url:
                filename = download_vod(vod_url)
                thumbnail_path = download_twitch_thumbnail(vod["thumbnail_url"])
                upload_to_youtube(
                    filename,
                    title,
                    description,
                    jst.strftime("%Y/%m/%d %H:%M"),
                    channel_url,
                    thumbnail_path,
                )
    print("📤 Twitchビデオなし")
    return None, None


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


def upload_to_youtube(
    file_path, title, description, created_at, channel_url, thumbnail_path
):
    print("📤 YouTubeにアップロード開始")
    youtube = build("youtube", "v3", credentials=creds)
    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        chunksize=1024 * 1024 * 8,  # 8MBごとに分割
        resumable=True,
    )
    account_name = channel_url.replace("https://www.twitch.tv/", "")
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": (
                    f"{created_at} Twitch配信のアーカイブ\n"
                    f"{description}\n\n"
                    f"チャンネル: {channel_url}\n"
                    f"X: https://x.com/{account_name}\n"
                ),
            },
            "status": {"privacyStatus": "private"},
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


def main():
    print("🚀 main.py 実行開始")
    execute()
    print("🚀 main.py 実行終了")


if __name__ == "__main__":
    main()
