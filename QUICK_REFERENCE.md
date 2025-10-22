# Media Conversion API - Quick Reference

## 🎵 Audio/Video to MP3 Conversion

### File Upload
```bash
POST /convert/mp3/file/
```
```python
files = {"file": open("video.mp4", "rb")}
data = {"bitrate": "192k"}  # 128k, 192k, 256k, 320k
```

### Base64
```bash
POST /convert/mp3/base64/
```
```json
{
  "file_base64": "...",
  "filename": "video.mp4",
  "bitrate": "192k"
}
```

**Supported:** MP4, M4A, MP3, WAV, AAC, FLAC, OGG, AVI, MOV, MKV

---

## 🎬 Video Compression

### File Upload
```bash
POST /convert/compress-video/file/
```
```python
files = {"file": open("video.mp4", "rb")}
data = {
    "resolution": "720p",  # 1080p, 720p, 480p, 360p
    "bitrate": "1000k"     # 1000k, 2000k, 3000k, etc.
}
```

### Base64
```bash
POST /convert/compress-video/base64/
```
```json
{
  "file_base64": "...",
  "filename": "video.mp4",
  "resolution": "720p",
  "bitrate": "1000k"
}
```

**Supported:** MP4 only

### Get Video Info
```bash
POST /convert/video-info/file/
```
Returns: duration, resolution, fps, has_audio

---

## 🖼️ Image to WebP Conversion

### File Upload
```bash
POST /convert/webp/file/
```
```python
files = {"file": open("image.png", "rb")}
data = {
    "quality": 80,        # 1-100
    "max_width": 1024,    # optional
    "max_height": None    # optional
}
```

### Base64
```bash
POST /convert/webp/base64/
```
```json
{
  "file_base64": "...",
  "filename": "image.png",
  "quality": 80,
  "max_width": 1024,
  "max_height": null
}
```

**Supported:** PNG, JPEG, JPG, BMP, TIFF, GIF

### Get Image Info
```bash
POST /convert/image-info/file/
```
Returns: format, dimensions, size, mode

---

## 📋 Response Format

All conversion endpoints return:
```json
{
  "success": true,
  "file_base64": "base64_encoded_output...",
  "original_filename": "input.mp4",
  "output_filename": "input.mp3",
  "input_size_kb": 5120.5,
  "output_size_kb": 3840.2,
  // ... additional conversion-specific info
}
```

---

## 🔑 Authentication

All endpoints require API key in header:
```python
headers = {"X-API-Key": "your_api_key"}
```

---

## 💡 Quick Tips

**MP3 Bitrate:**
- 128k = Lower quality, smaller size (voice)
- 192k = Standard quality (recommended)
- 320k = High quality (music)

**Video Resolution:**
- 1080p = Full HD
- 720p = HD (recommended)
- 480p/360p = Smaller sizes

**WebP Quality:**
- 70-80 = Balanced (recommended)
- 80-90 = High quality
- 90-100 = Maximum quality

---

## 🐍 Python Example - Complete Workflow

```python
import requests
import base64

API_URL = "http://localhost:8000"
API_KEY = "your_api_key"
headers = {"X-API-Key": API_KEY}

# 1. Convert video to MP3
with open("video.mp4", "rb") as f:
    response = requests.post(
        f"{API_URL}/convert/mp3/file/",
        headers=headers,
        files={"file": f},
        data={"bitrate": "192k"}
    )

result = response.json()
if result["success"]:
    # Save MP3
    with open("output.mp3", "wb") as f:
        f.write(base64.b64decode(result["file_base64"]))
    print(f"✓ Saved: {result['output_filename']}")

# 2. Compress video
with open("large_video.mp4", "rb") as f:
    response = requests.post(
        f"{API_URL}/convert/compress-video/file/",
        headers=headers,
        files={"file": f},
        data={"resolution": "720p", "bitrate": "2000k"}
    )

result = response.json()
if result["success"]:
    with open("compressed.mp4", "wb") as f:
        f.write(base64.b64decode(result["file_base64"]))
    print(f"✓ Reduced by {result['size_reduction_percent']}%")

# 3. Convert image to WebP
with open("image.png", "rb") as f:
    response = requests.post(
        f"{API_URL}/convert/webp/file/",
        headers=headers,
        files={"file": f},
        data={"quality": 85, "max_width": 1024}
    )

result = response.json()
if result["success"]:
    with open("image.webp", "wb") as f:
        f.write(base64.b64decode(result["file_base64"]))
    info = result["conversion_info"]
    print(f"✓ Size reduction: {info['size_reduction_percent']}%")
```

---

## 📦 Batch Processing Example

```python
import os
import requests
import base64

API_URL = "http://localhost:8000"
headers = {"X-API-Key": "your_api_key"}

def batch_convert_to_mp3(folder_path):
    """Convert all MP4 files in a folder to MP3"""
    for filename in os.listdir(folder_path):
        if filename.endswith('.mp4'):
            filepath = os.path.join(folder_path, filename)
            
            with open(filepath, "rb") as f:
                response = requests.post(
                    f"{API_URL}/convert/mp3/file/",
                    headers=headers,
                    files={"file": f},
                    data={"bitrate": "192k"}
                )
            
            if response.status_code == 200:
                result = response.json()
                output_name = result['output_filename']
                
                # Save MP3
                with open(output_name, "wb") as f:
                    f.write(base64.b64decode(result['file_base64']))
                
                print(f"✓ {filename} -> {output_name}")
            else:
                print(f"✗ Failed: {filename}")

# Usage
batch_convert_to_mp3("/path/to/videos")
```

---

## 🚀 API Documentation

Interactive documentation available at:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## ⚠️ Requirements

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **FFmpeg required** for moviepy:
   - Ubuntu/Debian: `sudo apt-get install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Windows: Download from https://ffmpeg.org/

3. **Run the API:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
