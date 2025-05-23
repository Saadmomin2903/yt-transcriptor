from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from urllib.parse import urlparse, parse_qs
import uvicorn
from os import getenv
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import json
import os

app = FastAPI()
current_dir = os.path.dirname(os.path.abspath(__file__))
cookie_path = os.path.join(current_dir, 'youtube_cookies.txt')

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Linkurl(BaseModel):
    url: HttpUrl
    languages: Optional[List[str]] = ["en"]

def extract_video_id(url_str):
    """Extract YouTube video ID from URL"""
    parsed_url = urlparse(url_str)
    
    # Handle youtube.com URLs
    if parsed_url.netloc in ('www.youtube.com', 'youtube.com'):
        if parsed_url.path == '/watch':
            query_params = parse_qs(parsed_url.query)
            if 'v' in query_params:
                return query_params['v'][0]
    
    # Handle youtu.be URLs
    elif parsed_url.netloc == 'youtu.be':
        return parsed_url.path.lstrip('/')
    
    # Handle URLs with /embed/ or /v/
    elif parsed_url.path.startswith(('/embed/', '/v/')):
        return parsed_url.path.split('/')[2]
    
    raise HTTPException(status_code=400, detail="Could not extract video ID from URL")

def get_transcript_with_ytdlp(video_url, preferred_langs=None, use_cookies=False):
    """Get transcript using yt-dlp"""
    if preferred_langs is None:
        preferred_langs = ['en']
    
    # Check if cookie file exists
    if use_cookies and not os.path.exists(cookie_path):
        print(f"Warning: Cookie file not found at {cookie_path}")
    
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': preferred_langs,
        'subtitlesformat': 'json3',
        'quiet': True,
        'no_warnings': True
    }
    
    # Only add cookie file if requested and it exists
    if use_cookies and os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get video info
            info = ydl.extract_info(video_url, download=False)
            
            # Get available subtitles
            subtitles = info.get('subtitles', {})
            auto_subtitles = info.get('automatic_captions', {})
            
            # Combine manual and auto-generated subtitles
            all_subtitles = {**subtitles, **auto_subtitles}
            
            if not all_subtitles:
                raise Exception("No subtitles available for this video")
            
            # Try to find subtitles in preferred languages
            subtitle_data = None
            used_language = None
            
            for lang in preferred_langs:
                if lang in all_subtitles:
                    subtitle_formats = all_subtitles[lang]
                    # Find json3 format
                    for format_info in subtitle_formats:
                        if format_info.get('ext') == 'json3':
                            subtitle_data = format_info
                            used_language = lang
                            break
                    if subtitle_data:
                        break
            
            # If preferred languages not found, use any available language
            if not subtitle_data:
                for lang, formats in all_subtitles.items():
                    for format_info in formats:
                        if format_info.get('ext') == 'json3':
                            subtitle_data = format_info
                            used_language = lang
                            break
                    if subtitle_data:
                        break
            
            if not subtitle_data:
                raise Exception("Could not find suitable subtitle format")
            
            # Download the subtitle file
            url = subtitle_data.get('url')
            if not url:
                raise Exception("Could not find subtitle URL")
            
            # Use yt-dlp's downloader to handle the request
            subtitle_content = ydl.urlopen(url).read().decode('utf-8')
            subtitle_json = json.loads(subtitle_content)
            
            # Extract transcript from the JSON3 format
            events = subtitle_json.get('events', [])
            
            transcript = []
            for event in events:
                if 'segs' in event:
                    start_time = event.get('tStartMs', 0) / 1000
                    duration = (event.get('dDurationMs', 0) / 1000) if 'dDurationMs' in event else 2.0
                    
                    text_parts = []
                    for seg in event.get('segs', []):
                        if 'utf8' in seg:
                            text_parts.append(seg['utf8'])
                    
                    if text_parts:
                        text = ''.join(text_parts).strip()
                        if text:  # Skip empty segments
                            transcript.append({
                                'text': text,
                                'start': start_time,
                                'duration': duration
                            })
            
            return transcript, used_language
    
    except Exception as e:
        raise Exception(f"Error extracting transcript: {str(e)}")

@app.post("/transcript")
async def get_youtube_transcript(link_request: Linkurl):
    try:
        url_str = str(link_request.url)
        video_id = extract_video_id(url_str)
        
        print(f"Processing video ID: {video_id}")
        
        # First try without cookies
        try:
            transcript, language = get_transcript_with_ytdlp(url_str, link_request.languages, use_cookies=False)
        except Exception as e:
            error_message = str(e)
            # If got auth error and we have cookies, retry with cookies
            if ("Sign in to confirm" in error_message or "bot" in error_message.lower()) and os.path.exists(cookie_path):
                print("Retrying with cookies...")
                try:
                    transcript, language = get_transcript_with_ytdlp(url_str, link_request.languages, use_cookies=True)
                except Exception as cookie_error:
                    print(f"Error with cookies: {str(cookie_error)}")
                    raise HTTPException(status_code=404, detail=f"Could not retrieve transcript even with cookies: {str(cookie_error)}")
            else:
                print(f"Error getting transcript: {error_message}")
                raise HTTPException(status_code=404, detail=f"Could not retrieve transcript: {error_message}")
        
        if not transcript:
            raise HTTPException(status_code=404, detail="No transcript found")
        
        # Format transcript to plain text
        transcript_text = " ".join(item["text"] for item in transcript)
        
        # Return full transcript data and formatted text
        return {
            "video_id": video_id,
            "transcript_text": transcript_text,
            "transcript_data": transcript,
            "language": language
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {
        "message": "YouTube Transcript API Service", 
        "status": "running",
        "usage": "POST to /transcript with YouTube URL to get transcript"
    }

@app.get("/debug")
async def debug_info():
    """Return debug information about the environment"""
    cookie_exists = os.path.exists(cookie_path)
    try:
        dir_contents = os.listdir(current_dir) if os.path.exists(current_dir) else "Directory not found"
    except Exception as e:
        dir_contents = f"Error listing directory: {str(e)}"
    
    return {
        "cookie_path": cookie_path,
        "cookie_file_exists": cookie_exists,
        "current_directory": current_dir,
        "directory_contents": dir_contents
    }

@app.get("/available-subtitles")
async def list_available_subtitles(url: str):
    """List all available subtitle languages for a YouTube video"""
    try:
        # First try without cookies
        try:
            ydl_opts = {
                'skip_download': True,
                'quiet': True,
                'no_warnings': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            error_message = str(e)
            # If got auth error and we have cookies, retry with cookies
            if ("Sign in to confirm" in error_message or "bot" in error_message.lower()) and os.path.exists(cookie_path):
                print("Retrying with cookies...")
                ydl_opts = {
                    'skip_download': True,
                    'quiet': True,
                    'no_warnings': True,
                    'cookiefile': cookie_path
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            else:
                raise Exception(error_message)
        
        subtitles = info.get('subtitles', {})
        auto_subtitles = info.get('automatic_captions', {})
        
        return {
            "video_id": info.get('id'),
            "title": info.get('title'),
            "manual_subtitles": list(subtitles.keys()),
            "automatic_subtitles": list(auto_subtitles.keys())
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing subtitles: {str(e)}")


if __name__ == '__main__':
    port = int(getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=True)

app = app