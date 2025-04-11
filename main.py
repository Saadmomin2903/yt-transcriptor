from fastapi import FastAPI
from pydantic import BaseModel, HttpUrl
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import uvicorn
from os import getenv

app = FastAPI()

class Linkurl(BaseModel):
    url: HttpUrl

@app.post("/transcript")
async def YTtranscript(Link_request: Linkurl):
    url_str = str(Link_request.url)
    parsed_url = urlparse(url_str)
    query_params = parse_qs(parsed_url.query)

    video_id = query_params['v'][0]
    print(video_id)
    ytt_api = YouTubeTranscriptApi()

    try:
        transcript = ytt_api.get_transcript(video_id, ("hi", "en"))
        transcript_text = " ".join(i["text"] for i in transcript)
        print(transcript_text)
        return transcript_text
    except Exception as e:
        print(f"Error: {str(e)}")  # Log the error for debugging
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == '__main__':
    port = int(getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=True)