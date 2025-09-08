from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import re
import sys

# YouTube認証
creds = Credentials.from_authorized_user_file("token.json")
if creds.expired:
    creds.refresh(Request())
youtube = build("youtube", "v3", credentials=creds)


def get_latest_video_in_playlist(playlist_id, index=1):
    """
    再生リストの最新から index 番目の動画IDを取得する
    index=0: 最新
    index=1: 最新から2番目
    """
    items = []
    nextPageToken = None
    while True:
        res = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=nextPageToken,
            )
            .execute()
        )
        items.extend(res.get("items", []))
        nextPageToken = res.get("nextPageToken")
        if not nextPageToken:
            break

    if len(items) == 0 or len(items) <= index:
        return None

    # 公開日（publishedAt）で降順ソート（新しい順）
    items_sorted = sorted(
        items, key=lambda x: x["snippet"].get("publishedAt", ""), reverse=True
    )
    return items_sorted[index]["snippet"]["resourceId"]["videoId"]


def update_video_details(edit_video_id, next_video_id):
    # 動画の詳細を編集
    # 既存情報取得
    video = (
        youtube.videos().list(part="snippet,localizations", id=edit_video_id).execute()
    )
    snippet = video["items"][0]["snippet"]
    if re.search(r"Next\s*→\s*そのうち", snippet.get("description", "")):
        return
    localizations = video["items"][0]["localizations"]
    if localizations:
        # descriptionのみ編集
        description_ja = localizations["ja"].get("description", "")
        # Next → そのうち を Next → ${play_list_link} に置換
        description_ja = re.sub(
            r"(Next\s*→\s*)そのうち", r"\1" + next_video_id, description_ja
        )
        localizations["ja"]["description"] = description_ja
        if "en" in localizations:
            # descriptionのみ編集
            description_en = localizations["en"].get("description", "")
            # 英語: Next → Soon を Next → ${play_list_link} に置換
            description_en = re.sub(
                r"(Next\s*→\s*)Soon", r"\1" + next_video_id, description_en
            )
            localizations["en"]["description"] = description_en
    else:
        description_ja = snippet.get("description", "")
        description_ja = re.sub(
            r"(Next\s*→\s*)そのうち", r"\1" + next_video_id, description_ja
        )
        localizations["ja"]["description"] = description_ja

    body = {
        "id": edit_video_id,
        "snippet": {
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
            "title": snippet.get("title"),
            "description": localizations["ja"]["description"],
            "tags": snippet.get("tags"),
            "categoryId": snippet.get("categoryId"),
        },
        "localizations": localizations,
    }
    youtube.videos().update(part="snippet,localizations", body=body).execute()


def extract_playlist_id(text: str) -> str | None:
    """
    文章中のYouTube再生リストURLからplaylistのIDを抽出する
    """
    # 正規表現でlist=以降のIDを取得
    match = re.search(r"list=([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1)
    return None


def main(playlist_id, next_video_id):
    edit_video_id = get_latest_video_in_playlist(playlist_id)
    if not edit_video_id:
        print("再生リストに動画がありません。")
    else:
        update_video_details(
            edit_video_id,
            next_video_id=f"https://youtube.com/{next_video_id}",
        )
        print("動画の詳細を更新しました。")


if __name__ == "__main__":
    # コマンドライン引数から playlist_id, video_id を取得
    if len(sys.argv) < 3:
        print("Usage: python update_my_list.py <PLAYLIST_ID> <VIDEO_ID>")
        sys.exit(1)
    playlist_id = sys.argv[1]
    next_video_id = sys.argv[2]
    main(playlist_id, next_video_id)
