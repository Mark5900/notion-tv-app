import logging
import os
import time
import urllib.request

import boto3
import requests
import schedule
from botocore.exceptions import BotoCoreError, ClientError
from bs4 import BeautifulSoup
from datetime import datetime
from PIL import Image, ImageFilter

# Constants and Configuration
SERVICE_NAME = "Notion TV"
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

USE_PUSHOVER = os.getenv("USE_PUSHOVER", "no").lower() == "yes"
USE_AWS = os.getenv("USE_AWS", "no").lower() == "yes"
AWS_CLEANUP = os.getenv("AWS_CLEANUP", "no").lower() == "yes"
BUCKET = os.getenv("AWS_BUCKET")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
PO_USER = os.getenv("PO_USER")
PO_TOKEN = os.getenv("PO_TOKEN")

# Select option names as they exist in the Notion database
TYPE_TV = "TV serie"
TYPE_MOVIE = "Movie"

NOTION_SUMMARY_LIMIT = 2000
HTTP_TIMEOUT = 30
PLACEHOLDER_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/c/ca/1x1.png"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

if not NOTION_TOKEN or not DATABASE_ID:
    raise SystemExit("NOTION_TOKEN and NOTION_DATABASE_ID must be set")

NOTION_headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Lookups that found nothing, keyed by (page_id, title). A page is retried
# only when its title changes, so unknown titles are not searched every minute.
failed_lookups = set()


# ---------------------------------------------------------------- helpers

def send_push(subject, message):
    """Send a Pushover notification; does nothing when Pushover is disabled."""
    if not USE_PUSHOVER or not PO_TOKEN or not PO_USER:
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PO_TOKEN, "user": PO_USER,
                  "title": str(subject), "message": str(message)},
            timeout=HTTP_TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        logging.error(f"Pushover failed: {e}")


def status():
    send_push(SERVICE_NAME + " is online",
              f"{SERVICE_NAME} is online and running at {datetime.now()}")


def remove_html(input_string):
    if not input_string:
        return ""
    return BeautifulSoup(input_string, "html.parser").get_text()


def get_json(url, params=None):
    """GET a JSON document. Returns None on 404 or any request error."""
    try:
        response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        if response.status_code == 404:
            return None
        if response.status_code == 429:  # TVmaze rate limit
            time.sleep(10)
            response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logging.error(f"Request to {url} failed: {e}")
        return None


def get_title(props):
    title = props.get("Name", {}).get("title") or []
    return "".join(part.get("plain_text") or part.get("text", {}).get("content", "")
                   for part in title).strip()


def get_select(props, name):
    select = (props.get(name) or {}).get("select")
    return select.get("name") if select else None


def get_number(props, name):
    return (props.get(name) or {}).get("number")


def date_value(value):
    return {"start": value} if value else None


def rich_text(value):
    return [{"type": "text", "text": {"content": (value or "")[:NOTION_SUMMARY_LIMIT]}}]


def title_text(value):
    return [{"type": "text", "text": {"content": value}}]


def episode_id_from_link(tv_data, link_name):
    href = ((tv_data.get("_links") or {}).get(link_name) or {}).get("href")
    if not href:
        return None
    try:
        return int(href.rstrip("/").split("/episodes/")[-1])
    except ValueError:
        return None


# ---------------------------------------------------------------- AWS

def upload_file(file_name, object_name=None):
    if object_name is None:
        object_name = os.path.basename(file_name)
    try:
        boto3.client("s3", region_name=AWS_REGION).upload_file(file_name, BUCKET, object_name)
        return True
    except (ClientError, BotoCoreError) as e:
        logging.error(f"S3 upload of {object_name} failed: {e}")
        return False


def s3_url(object_name):
    return f"https://{BUCKET}.s3.{AWS_REGION}.amazonaws.com/{object_name}"


def make_images(img_url, page_id):
    """Return (cover_url, poster_url).

    With AWS enabled a blurred banner and a resized poster are built and
    uploaded to S3. Without AWS, or if anything fails, the source image is used.
    """
    if not img_url:
        return PLACEHOLDER_IMAGE, PLACEHOLDER_IMAGE
    if not USE_AWS:
        return img_url, img_url

    img_name = f"{page_id}.jpg"
    poster_name = f"{page_id}_poster.jpg"
    try:
        urllib.request.urlretrieve(img_url, img_name)
        img = Image.open(img_name).convert("RGB")
        width, height = img.size

        new_height = 600
        img_poster = img.resize((int(new_height * width / height), new_height))
        img_poster.save(poster_name)

        banner = img.crop((5, height / 3, width, 2 * height / 3)).resize((1500, 600))
        banner = banner.filter(ImageFilter.BoxBlur(30))
        banner.paste(img_poster, (max(0, (1500 - img_poster.width) // 2), 0))
        banner.save(img_name)

        if upload_file(poster_name) and upload_file(img_name):
            return s3_url(img_name), s3_url(poster_name)
        return img_url, img_url
    except Exception as e:
        logging.error(f"Could not build banner for {page_id}: {e}")
        return img_url, img_url
    finally:
        for name in (img_name, poster_name):
            if os.path.exists(name):
                os.remove(name)


def cleanup_aws_images():
    """Delete images in S3 that don't belong to any current Notion page."""
    if not USE_AWS or not AWS_CLEANUP:
        return
    logging.info("Starting AWS S3 cleanup...")
    pages = get_pages()
    if not pages:
        logging.warning("No pages returned from Notion, skipping cleanup")
        return
    keep = set()
    for page in pages:
        keep.add(f"{page['id']}.jpg")
        keep.add(f"{page['id']}_poster.jpg")

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    deleted = 0
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for result in paginator.paginate(Bucket=BUCKET):
            for obj in result.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".jpg") and key not in keep:
                    s3_client.delete_object(Bucket=BUCKET, Key=key)
                    deleted += 1
        logging.info(f"AWS S3 cleanup completed. Deleted {deleted} unused images.")
        send_push("AWS S3 Cleanup Completed", f"Deleted {deleted} unused images from S3 bucket")
    except (ClientError, BotoCoreError) as e:
        logging.error(f"Error during S3 cleanup: {e}")
        send_push("AWS S3 Cleanup Failed", e)


# ---------------------------------------------------------------- TVmaze

def get_tv_by_name(title):
    return get_json("https://api.tvmaze.com/singlesearch/shows", {"q": title})


def get_tv_by_id(tv_id):
    if tv_id is None:
        return None
    return get_json(f"https://api.tvmaze.com/shows/{int(tv_id)}")


def get_episode_stats(tv_id):
    """Return (season_count, episode_count) for regular episodes, specials excluded.

    TVmaze's per-season episodeOrder is often empty, so the episode list is
    counted instead. Scheduled future episodes are included.
    """
    episodes = get_json(f"https://api.tvmaze.com/shows/{int(tv_id)}/episodes")
    if episodes:
        regular = [ep for ep in episodes if ep.get("type", "regular") == "regular"]
        seasons = {ep.get("season") for ep in regular if ep.get("season") is not None}
        return len(seasons), len(regular)

    seasons = get_json(f"https://api.tvmaze.com/shows/{int(tv_id)}/seasons") or []
    return len(seasons), sum(s.get("episodeOrder") or 0 for s in seasons)


def update_tv_data(tv_data, page_id):
    tv_id = tv_data["id"]
    name = tv_data.get("name")
    logging.info(f"Updating TV show '{name}' (tvmaze {tv_id})")

    season_count, total_episodes = get_episode_stats(tv_id)
    img_url = (tv_data.get("image") or {}).get("original")
    cover, poster = make_images(img_url, page_id)

    properties = {
        "TVDBID": {"number": (tv_data.get("externals") or {}).get("thetvdb")},
        "tvmazeID": {"number": tv_id},
        "Type": {"select": {"name": TYPE_TV}},
        "Premiered": {"date": date_value(tv_data.get("premiered"))},
        "Ended": {"date": date_value(tv_data.get("ended"))},
        "Last Aired Episode": {"number": episode_id_from_link(tv_data, "previousepisode")},
        "Seasons": {"number": season_count},
        "Total Eps.": {"number": total_episodes},
        "Summary": {"rich_text": rich_text(remove_html(tv_data.get("summary")))},
        "Poster": {"files": [{"name": "Poster", "type": "external", "external": {"url": poster}}]},
    }
    if tv_data.get("status"):
        properties["Show Status"] = {"select": {"name": tv_data["status"]}}
    if name:
        properties["Name"] = {"title": title_text(name)}

    return update_page(page_id, {"cover": {"external": {"url": cover}}, "properties": properties})


# ---------------------------------------------------------------- TMDb

def get_movie_by_name(title):
    if not TMDB_API_KEY:
        logging.warning("TMDB_API_KEY is not set, cannot look up movies")
        return None
    data = get_json("https://api.themoviedb.org/3/search/movie",
                    {"api_key": TMDB_API_KEY, "query": title})
    if not data or not data.get("results"):
        return None
    return get_movie_by_id(data["results"][0]["id"])


def get_movie_by_id(movie_id):
    if not TMDB_API_KEY or movie_id is None:
        return None
    return get_json(f"https://api.themoviedb.org/3/movie/{int(movie_id)}",
                    {"api_key": TMDB_API_KEY})


def update_movie_data(movie_data, page_id):
    name = movie_data.get("title")
    logging.info(f"Updating movie '{name}' (tmdb {movie_data['id']})")

    poster_path = movie_data.get("poster_path")
    img_url = f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else None
    cover, poster = make_images(img_url, page_id)

    properties = {
        "tmdbID": {"number": movie_data["id"]},
        "Type": {"select": {"name": TYPE_MOVIE}},
        "Premiered": {"date": date_value(movie_data.get("release_date"))},
        "Runtime": {"number": movie_data.get("runtime") or None},
        "Summary": {"rich_text": rich_text(movie_data.get("overview"))},
        "Poster": {"files": [{"name": "Poster", "type": "external", "external": {"url": poster}}]},
    }
    if movie_data.get("status"):
        properties["Show Status"] = {"select": {"name": movie_data["status"]}}
    if name:
        properties["Name"] = {"title": title_text(name)}

    return update_page(page_id, {"cover": {"external": {"url": cover}}, "properties": properties})


# ---------------------------------------------------------------- Notion

def get_pages():
    """Return all pages in the database, or [] if Notion can't be reached."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {"page_size": 100}
    results = []
    while True:
        try:
            response = requests.post(url, json=payload, headers=NOTION_headers, timeout=HTTP_TIMEOUT)
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logging.error(f"Error fetching Notion pages: {e}")
            return []
        if "results" not in data:
            logging.error(f"Error fetching Notion pages: {data}")
            return []
        results.extend(data["results"])
        if not data.get("has_more"):
            return results
        payload["start_cursor"] = data["next_cursor"]


def update_page(page_id, data):
    try:
        res = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                             json=data, headers=NOTION_headers, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as e:
        logging.error(f"Notion update of {page_id} failed: {e}")
        return False
    if res.status_code == 200:
        logging.info("Notion page updated")
        return True
    try:
        error = res.json()
    except ValueError:
        error = {"message": res.text}
    logging.error(f"Notion update of {page_id} failed ({res.status_code}): {error}")
    send_push(f"{error.get('status', res.status_code)}: {error.get('code', 'error')}",
              error.get("message", "No error message"))
    return False


# ---------------------------------------------------------------- jobs

def read_pages():
    """Fill in pages that have a name but no tvmazeID / tmdbID yet."""
    for page in get_pages():
        page_id = page.get("id")
        title = ""
        try:
            props = page["properties"]
            title = get_title(props)
            if not title:
                continue

            content_type = get_select(props, "Type")
            is_movie = content_type == TYPE_MOVIE
            if get_number(props, "tmdbID" if is_movie else "tvmazeID") is not None:
                continue
            if (page_id, title) in failed_lookups:
                continue

            search_title = title.replace(";", "")
            if is_movie:
                data = get_movie_by_name(search_title)
                ok = data is not None and update_movie_data(data, page_id)
            else:
                data = get_tv_by_name(search_title)
                ok = data is not None and update_tv_data(data, page_id)

            if not ok:
                logging.warning(f"No match for '{title}' ({content_type or 'no type'}); "
                                "retrying when the title changes")
                failed_lookups.add((page_id, title))
        except Exception as e:
            logging.exception(f"Error processing page {page_id} '{title}': {e}")
            failed_lookups.add((page_id, title))


def new_ep_check():
    """Weekly refresh: new episodes / status changes for shows, status for unreleased movies."""
    for page in get_pages():
        page_id = page.get("id")
        title = ""
        try:
            props = page["properties"]
            title = get_title(props)

            tv_id = get_number(props, "tvmazeID")
            if tv_id is not None:
                tv_data = get_tv_by_id(tv_id)
                if not tv_data:
                    continue
                changed = (
                    get_number(props, "Last Aired Episode") != episode_id_from_link(tv_data, "previousepisode")
                    or get_select(props, "Show Status") != tv_data.get("status")
                )
                if changed:
                    logging.info(f"'{title}' has changed on TVmaze, updating")
                    update_tv_data(tv_data, page_id)
                continue

            tmdb_id = get_number(props, "tmdbID")
            if tmdb_id is not None and get_select(props, "Show Status") not in ("Released", "Canceled"):
                movie_data = get_movie_by_id(tmdb_id)
                if movie_data and movie_data.get("status") != get_select(props, "Show Status"):
                    logging.info(f"Movie '{title}' status changed, updating")
                    update_movie_data(movie_data, page_id)
        except Exception as e:
            logging.exception(f"Error checking page {page_id} '{title}': {e}")


def safe(job):
    """Wrap a scheduled job so an unexpected error never stops the scheduler."""
    def wrapper():
        try:
            job()
        except Exception as e:
            logging.exception(f"{job.__name__} failed: {e}")
    wrapper.__name__ = job.__name__
    return wrapper


if __name__ == "__main__":
    if AWS_CLEANUP:
        safe(cleanup_aws_images)()
        schedule.every().day.do(safe(cleanup_aws_images))
        logging.info("AWS cleanup scheduled to run daily")

    schedule.every(60).seconds.do(safe(read_pages))
    schedule.every().sunday.at("22:00").do(safe(new_ep_check))
    logging.info("Next scan scheduled...")

    while True:
        schedule.run_pending()
        time.sleep(1)
