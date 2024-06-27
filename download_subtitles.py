import asyncio
import aiohttp
import m3u8
import re
import sys
import os
import hashlib
from urllib.parse import urlparse, urljoin
import webvtt
from datetime import timedelta

CACHE_DIR = ".cache"

def get_cache_filename(url):
    return os.path.join(CACHE_DIR, hashlib.md5(url.encode()).hexdigest() + ".txt")

async def fetch(session, url):
    cache_filename = get_cache_filename(url)
    if os.path.exists(cache_filename):
        with open(cache_filename, 'r', encoding='utf-8') as f:
            return f.read()
    
    async with session.get(url) as response:
        content = await response.text()
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return content
    
def parse_timestamp(timestamp):
    hours, minutes, seconds = timestamp.split(':')
    return timedelta(hours=int(hours), minutes=int(minutes), seconds=float(seconds))


def parse_vtt_fragment(content):
    pattern = r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})(.*?)(?=\n\d{2}:\d{2}:\d{2}\.\d{3}|$)'
    matches = re.findall(pattern, content, re.DOTALL)
    return [webvtt.Caption(start, end, text.strip()) for start, end, text in matches]

async def download_and_concatenate_subtitles(m3u8_url, output_filename=None):
    try:
        parsed_url = urlparse(m3u8_url)
        if output_filename is None:
            base_filename = os.path.splitext(os.path.basename(parsed_url.path))[0]
            output_filename = f"{base_filename}_english_subtitles.vtt"

        async with aiohttp.ClientSession() as session:
            print(f"Attempting to download: {m3u8_url}")
            async with session.get(m3u8_url) as response:
                m3u8_content = await response.text()

            playlist = m3u8.loads(m3u8_content)

            english_subtitle_uri = next((media.uri for media in playlist.media 
                                         if media.type == "SUBTITLES" and media.language == "en"), None)

            if not english_subtitle_uri:
                print("English subtitles not found.")
                return

            english_subtitle_uri = urljoin(m3u8_url, english_subtitle_uri)

            print(f"Downloading English subtitles from: {english_subtitle_uri}")
            async with session.get(english_subtitle_uri) as response:
                subtitle_m3u8_content = await response.text()
            subtitle_playlist = m3u8.loads(subtitle_m3u8_content)

            segment_uris = [urljoin(english_subtitle_uri, segment.uri) for segment in subtitle_playlist.segments]
            
            print(f"Downloading {len(segment_uris)} subtitle segments...")

            lines = []

            for uri in segment_uris:
                segment_content = await fetch(session, uri)
                segment_captions = parse_vtt_fragment(segment_content)
                for caption in segment_captions:
                    content = re.sub(r'align\:.*?\n', '', caption.text.strip())
                    content = re.sub(r'♪.+♪$', '', content)
                    content = re.sub(r'\n', ' ', content)
                    content = re.sub(r'[^a-zA-Z0-9\'\:\-\s\.\,\?\!]+', '', content)
                    content = re.sub(r'\s{2}+', ' ', content)
                    if not lines:
                        lines.append(content.strip())
                    elif 0 < content.find(':') < 20 and not lines[-1].startswith(content.strip()):
                        lines.append(content.strip())
                    else:
                        lines[-1] = (lines[-1] + ' ' + content).strip()

            with open(output_filename, "w", encoding="utf-8") as f:
                f.write('\n'.join(lines))

            print(f"Merged subtitles have been saved to '{output_filename}'")

    except aiohttp.ClientError as e:
        print(f"An error occurred while making a request: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise  # This will print the full traceback

if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python script.py <m3u8_url> [output_filename]")
        sys.exit(1)

    m3u8_url = sys.argv[1]
    output_filename = sys.argv[2] if len(sys.argv) == 3 else None
    asyncio.run(download_and_concatenate_subtitles(m3u8_url, output_filename))