import asyncio
import aiohttp
import m3u8
import re
import sys
import os
import hashlib
from urllib.parse import urlparse, urljoin

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

def clean_webvtt(content):
    # Remove WebVTT headers, timestamp lines, and other metadata
    content = re.sub(r'WEBVTT.*?\n', '', content, flags=re.DOTALL)
    content = re.sub(r'X-TIMESTAMP-MAP=.*?\n', '', content)
    content = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}.*?\n', '', content)
    
    # Split content into lines and remove empty lines
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    
    cleaned_lines = []
    current_speaker = ""
    current_text = ""

    def add_current_text():
        nonlocal current_speaker, current_text, cleaned_lines
        if current_text:
            if current_speaker:
                if current_speaker[0].isupper():  # It's a human speaker
                    cleaned_lines.append('')  # Add extra newline before human speaker
                    cleaned_lines.append(f"{current_speaker}: {current_text.strip()}")
                else:  # It's an effect
                    cleaned_lines.append(f"[{current_speaker}]")
                    if current_text.strip():
                        cleaned_lines.append(current_text.strip())
            else:
                cleaned_lines.append(current_text.strip())
            current_text = ""

    for line in lines:
        if line.startswith('['):
            add_current_text()
            # Remove opening and closing brackets, and strip any whitespace
            current_speaker = line.strip('[]').strip()
        else:
            current_text += " " + line if current_text else line

    add_current_text()  # Add any remaining text

    return '\n'.join(cleaned_lines)

async def download_and_concatenate_subtitles(m3u8_url, output_filename=None):
    try:
        parsed_url = urlparse(m3u8_url)
        if output_filename is None:
            base_filename = os.path.splitext(os.path.basename(parsed_url.path))[0]
            output_filename = f"{base_filename}_english_subtitles.txt"

        async with aiohttp.ClientSession() as session:
            print(f"Attempting to download: {m3u8_url}")
            m3u8_content = await fetch(session, m3u8_url)

            playlist = m3u8.loads(m3u8_content)

            english_subtitle_uri = next((media.uri for media in playlist.media 
                                         if media.type == "SUBTITLES" and media.language == "en"), None)

            if not english_subtitle_uri:
                print("English subtitles not found.")
                return

            english_subtitle_uri = urljoin(m3u8_url, english_subtitle_uri)

            print(f"Downloading English subtitles from: {english_subtitle_uri}")
            subtitle_m3u8_content = await fetch(session, english_subtitle_uri)
            subtitle_playlist = m3u8.loads(subtitle_m3u8_content)

            segment_uris = [urljoin(english_subtitle_uri, segment.uri) for segment in subtitle_playlist.segments]
            
            print(f"Downloading {len(segment_uris)} subtitle segments...")
            tasks = [fetch(session, uri) for uri in segment_uris]
            subtitle_contents = await asyncio.gather(*tasks)

            full_subtitles = "\n".join(subtitle_contents)
            cleaned_subtitles = clean_webvtt(full_subtitles)

            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(cleaned_subtitles)

            print(f"Cleaned subtitles have been saved to '{output_filename}'")

    except aiohttp.ClientError as e:
        print(f"An error occurred while making a request: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python script.py <m3u8_url> [output_filename]")
        sys.exit(1)

    m3u8_url = sys.argv[1]
    output_filename = sys.argv[2] if len(sys.argv) == 3 else None
    asyncio.run(download_and_concatenate_subtitles(m3u8_url, output_filename))