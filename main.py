import os, json, random, asyncio, subprocess, textwrap, urllib.parse, glob
import requests
from PIL import Image, ImageDraw, ImageFont
import edge_tts

LANG = os.getenv("RHYME_LANG", "english").lower()  # english / hindi / marathi
MODEL = os.getenv("GEMINI_MODEL", gemini-3.5-flash)
KEY = os.environ["GEMINI_API_KEY"]
VOICES = {"english": "en-US-AnaNeural", "hindi": "hi-IN-SwaraNeural", "marathi": "mr-IN-AarohiNeural"}
TOPICS = ["a little duck", "the moon and stars", "a happy elephant", "rainy day", "colors of the rainbow",
          "a brave little bunny", "baby chick", "monkey on a tree", "a sleepy kitten", "my school bus",
          "fruits and vegetables", "a tiny butterfly", "brushing teeth", "a friendly lion", "counting 1 to 10"]
W, H = 1280, 720
OUT = "out"
os.makedirs(OUT, exist_ok=True)


def make_rhyme(topic):
    prompt = (f"Write a cute, original kids nursery rhyme in {LANG} about: {topic}. "
              'Return ONLY JSON: {"title": "...", "description": "...", "lines": '
              '[{"text": "rhyme line in the target language", "image": "English description of a bright cartoon scene"}]}. '
              "Use 8 to 12 short rhyming lines, very simple words, safe for toddlers.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
                                 "generationConfig": {"responseMimeType": "application/json"}}, timeout=90)
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def get_image(prompt, i):
    path = f"{OUT}/img{i}.png"
    try:
        u = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote("cute colorful cartoon for kids, " + prompt)
             + f"?width={W}&height={H}&nologo=true&seed={random.randint(1, 99999)}")
        r = requests.get(u, timeout=120)
        r.raise_for_status()
        open(path, "wb").write(r.content)
        Image.open(path).convert("RGB").resize((W, H)).save(path)
    except Exception as e:
        print("image fallback:", e)
        Image.new("RGB", (W, H), random.choice([(255, 214, 102), (129, 212, 250), (165, 214, 167)])).save(path)
    return path


def find_font():
    names = ["NotoSansDevanagari-Bold.ttf", "DejaVuSans-Bold.ttf"] if LANG != "english" else ["DejaVuSans-Bold.ttf"]
    for n in names:
        found = glob.glob(f"/usr/share/fonts/**/{n}", recursive=True)
        if found:
            return found[0]
    return None


FONT = find_font()


def add_caption(path, text):
    img = Image.open(path).convert("RGBA")
    font = ImageFont.truetype(FONT, 56) if FONT else ImageFont.load_default()
    lines = textwrap.wrap(text, 32)
    y = H - 60 - len(lines) * 72
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, y - 20, W, H], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img)
    for k, line in enumerate(lines):
        d.text((W / 2, y + k * 72), line, font=font, fill="white", anchor="ma")
    img.convert("RGB").save(path)


async def tts(text, path):
    await edge_tts.Communicate(text, VOICES[LANG], rate="-10%", pitch="+10Hz").save(path)


def build_video(lines):
    clips = []
    for i, l in enumerate(lines):
        img = get_image(l["image"], i)
        add_caption(img, l["text"])
        mp3 = f"{OUT}/a{i}.mp3"
        asyncio.run(tts(l["text"], mp3))
        clip = f"{OUT}/s{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", mp3, "-af", "apad=pad_dur=0.5",
                        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "24",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest", clip], check=True)
        clips.append(clip)
    with open(f"{OUT}/list.txt", "w") as f:
        for c in clips:
            f.write(f"file '{os.path.basename(c)}'\n")
    final = f"{OUT}/final.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{OUT}/list.txt", "-c", "copy", final], check=True)
    return final


def upload(path, title, desc):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:95], "description": desc + "\n\n#kidsrhymes #nurseryrhymes",
                        "tags": ["kids rhymes", "nursery rhymes", "baby songs"], "categoryId": "24"},
            "status": {"privacyStatus": os.getenv("PRIVACY", "private"), "selfDeclaredMadeForKids": True}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(path, chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print("Uploaded: https://youtube.com/watch?v=" + resp["id"])


if __name__ == "__main__":
    topic = random.choice(TOPICS)
    print("Topic:", topic)
    data = make_rhyme(topic)
    final = build_video(data["lines"])
    if os.getenv("YT_REFRESH_TOKEN"):
        upload(final, data["title"], data.get("description", ""))
    else:
        print("YouTube secrets not set - video saved only as artifact.")
