import os
import uuid
import logging
import httpx
from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv

# --- Configuration & Setup ---
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

HF_API_TOKEN = os.getenv("HF_API_TOKEN")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
HF_API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2"
VOICE_ID = "VOICE_ID"
AUDIO_DIR = "audio_cache"

app = FastAPI(title="Post-Op Triage Voice Bot")
os.makedirs(AUDIO_DIR, exist_ok=True)

SYSTEM_PROMPT = """You are a compassionate, slow-speaking medical assistant checking in on a post-operation patient over 60 years old. 
Keep your responses incredibly brief (1 to 2 sentences maximum). Do not use complex medical jargon. Ask one clear question at a time about their pain levels, medication, or general comfort."""

# --- Core Asynchronous Services ---

async def generate_llm_response(user_text: str) -> str:
    """Fetches completion from Hugging Face asynchronously."""
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    prompt = f"<s>[INST] {SYSTEM_PROMPT}\n\nPatient says: {user_text} [/INST]"
    payload = {
        "inputs": prompt, 
        "parameters": {"max_new_tokens": 60, "temperature": 0.2}
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(HF_API_URL, headers=headers, json=payload)
            res.raise_for_status()
            output = res.json()[0]['generated_text']
            return output.split("[/INST]")[-1].strip()
        except httpx.HTTPError as e:
            logger.error(f"LLM API Communication Error: {e}")
            return "I'm having a little trouble hearing you. Could you repeat how you are feeling?"
        except (KeyError, IndexError) as e:
            logger.error(f"LLM API Parsing Error: {e}")
            return "I missed that. How are you feeling today?"

async def generate_tts_audio(text: str) -> str:
    """Generates TTS via ElevenLabs and saves temporarily, returning the filename."""
    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {"stability": 0.7, "similarity_boost": 0.7}
    }
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(url, json=data, headers=headers)
            res.raise_for_status()
            
            # Asynchronous file writing (for ultra-high scale use aiofiles, 
            # but blocking I/O for small MP3s is generally acceptable here)
            with open(filepath, "wb") as f:
                f.write(res.content)
                
            return filename
        except httpx.HTTPError as e:
            logger.error(f"TTS Generation Error: {e}")
            raise HTTPException(status_code=502, detail="Failed to generate audio")

def cleanup_audio_file(filepath: str):
    """Background task to delete audio files after Twilio fetches them."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Cleaned up audio file: {filepath}")
    except Exception as e:
        logger.error(f"Failed to delete {filepath}: {e}")

# --- API Endpoints ---

@app.post("/voice")
async def voice_endpoint(request: Request):
    """Handles incoming Twilio webhooks and orchestrates the response."""
    form_data = await request.form()
    user_speech = form_data.get("SpeechResult")
    
    response = VoiceResponse()
    base_url = str(request.base_url).rstrip("/")

    if user_speech:
        logger.info(f"Patient input captured: {user_speech}")
        ai_text = await generate_llm_response(user_speech)
        audio_filename = await generate_tts_audio(ai_text)
        response.play(f"{base_url}/audio/{audio_filename}")

    gather = Gather(input="speech", action="/voice", timeout=4, speechTimeout="auto")
    
    if not user_speech:
        logger.info("Initiating new call flow.")
        greeting = "Hello. I am calling to check on your post-operation recovery. How are you feeling today?"
        audio_filename = await generate_tts_audio(greeting)
        gather.play(f"{base_url}/audio/{audio_filename}")
        
    response.append(gather)
    response.redirect("/voice")
    
    return Response(content=str(response), media_type="application/xml")

@app.get("/audio/{filename}")
async def get_audio(filename: str, background_tasks: BackgroundTasks):
    """Serves the audio file to Twilio and schedules it for deletion."""
    filepath = os.path.join(AUDIO_DIR, filename)
    
    if not os.path.exists(filepath):
        logger.warning(f"Requested audio file not found: {filepath}")
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    # Schedule the cleanup task to run AFTER the response is sent to Twilio
    background_tasks.add_task(cleanup_audio_file, filepath)
    
    return FileResponse(filepath, media_type="audio/mpeg")

if __name__ == "__main__":
    import uvicorn
    # In production, run via command line: uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)