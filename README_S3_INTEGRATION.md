# Media & Image Converter API with S3 Storage Integration

## Overview

Enhanced FastAPI application that converts media files (video/audio) and images with automatic S3 storage and direct download URL generation.

## Key Features

### 🎵 Media Conversion with S3
- **MP4 to MP3 conversion** with configurable bitrate
- **Video compression** with resolution and bitrate control
- **Automatic S3 upload** with public download URLs
- **Flexible response options**: Base64, S3 URL, or both

### 🖼️ Image Conversion with S3
- **Image to WebP conversion** with quality control
- **Smart resizing** while maintaining aspect ratio
- **S3 storage** for converted images
- **Multiple format support**: PNG, JPEG, BMP, TIFF, GIF

## S3 Configuration

### Environment Variables

```bash
# Required for S3 functionality
S3_BUCKET=www.aloraloy.com
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key

# API Configuration
DEFAULT_API_KEY=Pass#0123456789#?
```

### S3 Bucket Setup

1. **Create S3 bucket**: `www.aloraloy.com`
2. **Configure bucket policy** for public read access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::www.aloraloy.com/convert-it/converted/*"
    }
  ]
}
```

3. **Disable Block Public Access** for the specific folder
4. **Enable ACLs** in bucket settings

## Installation

```bash
# Install dependencies
pip install fastapi uvicorn boto3 botocore pillow moviepy psycopg2-binary --break-system-packages

# Run the server
python main_with_s3.py
```

## API Endpoints

### Media Conversion

#### 1. Convert to MP3 (File Upload)

```bash
curl -X POST "http://localhost:8000/convert/mp3/file/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -F "file=@video.mp4" \
  -F "bitrate=192k" \
  -F "use_s3=true" \
  -F "return_base64=false"
```

**Response:**
```json
{
  "success": true,
  "original_filename": "video.mp4",
  "output_filename": "video.mp3",
  "bitrate": "192k",
  "output_size_mb": 4.52,
  "download_url": "https://www.aloraloy.com/convert-it/converted/20251022_143052_video.mp3",
  "expires_at": "2025-11-21T14:30:52.123456"
}
```

#### 2. Convert to MP3 (Base64)

```bash
curl -X POST "http://localhost:8000/convert/mp3/base64/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -H "Content-Type: application/json" \
  -d '{
    "file_base64": "BASE64_ENCODED_FILE",
    "filename": "video.mp4",
    "bitrate": "192k",
    "use_s3": true,
    "return_base64": false
  }'
```

#### 3. Compress Video (File Upload)

```bash
curl -X POST "http://localhost:8000/convert/compress-video/file/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -F "file=@large_video.mp4" \
  -F "resolution=720p" \
  -F "bitrate=1000k" \
  -F "use_s3=true" \
  -F "return_base64=false"
```

**Response:**
```json
{
  "success": true,
  "original_filename": "large_video.mp4",
  "output_filename": "large_video_720p.mp4",
  "resolution": "720p",
  "bitrate": "1000k",
  "input_size_mb": 125.3,
  "output_size_mb": 42.7,
  "size_reduction_percent": 65.9,
  "download_url": "https://www.aloraloy.com/convert-it/converted/20251022_143100_large_video_720p.mp4",
  "expires_at": "2025-11-21T14:31:00.123456"
}
```

### Image Conversion

#### 4. Convert to WebP (File Upload)

```bash
curl -X POST "http://localhost:8000/convert/webp/file/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -F "file=@image.png" \
  -F "quality=80" \
  -F "max_width=1920" \
  -F "use_s3=true" \
  -F "return_base64=false"
```

**Response:**
```json
{
  "success": true,
  "conversion_info": {
    "original_filename": "image.png",
    "output_filename": "image.webp",
    "original_size_kb": 2048.5,
    "output_size_kb": 512.3,
    "size_reduction_percent": 75.0,
    "original_dimensions": {
      "width": 3840,
      "height": 2160
    },
    "output_dimensions": {
      "width": 1920,
      "height": 1080
    },
    "was_resized": true,
    "quality": 80
  },
  "download_url": "https://www.aloraloy.com/convert-it/converted/20251022_143105_image.webp",
  "expires_at": "2025-11-21T14:31:05.123456"
}
```

#### 5. Convert to WebP (Base64)

```bash
curl -X POST "http://localhost:8000/convert/webp/base64/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -H "Content-Type: application/json" \
  -d '{
    "file_base64": "BASE64_ENCODED_IMAGE",
    "filename": "photo.jpg",
    "quality": 85,
    "max_width": 1200,
    "use_s3": true,
    "return_base64": false
  }'
```

## Request Parameters

### Media Conversion Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` or `file_base64` | File/String | Required | Input file |
| `filename` | String | Required | Original filename |
| `bitrate` | String | `"192k"` | Audio bitrate (128k, 192k, 256k, 320k) |
| `resolution` | String | `"720p"` | Video resolution (1080p, 720p, 480p, 360p) |
| `use_s3` | Boolean | `false` | Upload to S3 and return URL |
| `return_base64` | Boolean | `true` | Include base64 in response |

### Image Conversion Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` or `file_base64` | File/String | Required | Input image |
| `filename` | String | Required | Original filename |
| `quality` | Integer | `80` | WebP quality (1-100) |
| `max_width` | Integer | `None` | Maximum width in pixels |
| `max_height` | Integer | `None` | Maximum height in pixels |
| `use_s3` | Boolean | `false` | Upload to S3 and return URL |
| `return_base64` | Boolean | `true` | Include base64 in response |

## Response Options

### Option 1: S3 URL Only (Recommended for large files)

```python
{
    "use_s3": True,
    "return_base64": False
}
```

**Benefits:**
- Smaller response payload
- Direct download link
- CDN-ready URLs
- No size limitations

### Option 2: Base64 Only (No S3)

```python
{
    "use_s3": False,
    "return_base64": True
}
```

**Benefits:**
- Immediate data availability
- No external dependencies
- Works offline

### Option 3: Both (Maximum flexibility)

```python
{
    "use_s3": True,
    "return_base64": True
}
```

**Benefits:**
- Fallback option
- Immediate + persistent access
- Best for critical files

## Python Client Example

```python
import requests
import base64

# Configuration
API_URL = "http://localhost:8000"
API_KEY = "Pass#0123456789#?"

def convert_video_to_mp3(video_path: str, use_s3: bool = True):
    """Convert video to MP3 and get S3 download URL"""
    
    with open(video_path, 'rb') as f:
        files = {'file': f}
        data = {
            'bitrate': '192k',
            'use_s3': use_s3,
            'return_base64': False
        }
        headers = {'X-API-Key': API_KEY}
        
        response = requests.post(
            f"{API_URL}/convert/mp3/file/",
            files=files,
            data=data,
            headers=headers
        )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Conversion successful!")
        print(f"  Download URL: {result['download_url']}")
        print(f"  Expires: {result['expires_at']}")
        print(f"  Size: {result['output_size_mb']} MB")
        return result['download_url']
    else:
        print(f"✗ Error: {response.json()}")
        return None

def convert_image_to_webp(image_path: str, quality: int = 80):
    """Convert image to WebP with S3 upload"""
    
    with open(image_path, 'rb') as f:
        files = {'file': f}
        data = {
            'quality': quality,
            'max_width': 1920,
            'use_s3': True,
            'return_base64': False
        }
        headers = {'X-API-Key': API_KEY}
        
        response = requests.post(
            f"{API_URL}/convert/webp/file/",
            files=files,
            data=data,
            headers=headers
        )
    
    if response.status_code == 200:
        result = response.json()
        info = result['conversion_info']
        print(f"✓ Conversion successful!")
        print(f"  Download URL: {result['download_url']}")
        print(f"  Size reduction: {info['size_reduction_percent']}%")
        print(f"  Dimensions: {info['output_dimensions']['width']}x{info['output_dimensions']['height']}")
        return result['download_url']
    else:
        print(f"✗ Error: {response.json()}")
        return None

# Usage
if __name__ == "__main__":
    # Convert video to MP3
    mp3_url = convert_video_to_mp3("video.mp4")
    
    # Convert image to WebP
    webp_url = convert_image_to_webp("photo.jpg", quality=85)
```

## JavaScript/Node.js Client Example

```javascript
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');

const API_URL = 'http://localhost:8000';
const API_KEY = 'Pass#0123456789#?';

async function convertVideoToMP3(videoPath, useS3 = true) {
    const form = new FormData();
    form.append('file', fs.createReadStream(videoPath));
    form.append('bitrate', '192k');
    form.append('use_s3', useS3);
    form.append('return_base64', false);
    
    try {
        const response = await axios.post(
            `${API_URL}/convert/mp3/file/`,
            form,
            {
                headers: {
                    'X-API-Key': API_KEY,
                    ...form.getHeaders()
                }
            }
        );
        
        console.log('✓ Conversion successful!');
        console.log(`  Download URL: ${response.data.download_url}`);
        console.log(`  Size: ${response.data.output_size_mb} MB`);
        return response.data.download_url;
    } catch (error) {
        console.error('✗ Error:', error.response?.data || error.message);
        return null;
    }
}

async function convertImageToWebP(imagePath, quality = 80) {
    const form = new FormData();
    form.append('file', fs.createReadStream(imagePath));
    form.append('quality', quality);
    form.append('max_width', 1920);
    form.append('use_s3', true);
    form.append('return_base64', false);
    
    try {
        const response = await axios.post(
            `${API_URL}/convert/webp/file/`,
            form,
            {
                headers: {
                    'X-API-Key': API_KEY,
                    ...form.getHeaders()
                }
            }
        );
        
        const info = response.data.conversion_info;
        console.log('✓ Conversion successful!');
        console.log(`  Download URL: ${response.data.download_url}`);
        console.log(`  Size reduction: ${info.size_reduction_percent}%`);
        return response.data.download_url;
    } catch (error) {
        console.error('✗ Error:', error.response?.data || error.message);
        return null;
    }
}

// Usage
(async () => {
    await convertVideoToMP3('video.mp4');
    await convertImageToWebP('photo.jpg', 85);
})();
```

## S3 File Structure

```
www.aloraloy.com/
└── convert-it/
    └── converted/
        ├── 20251022_143052_video.mp3
        ├── 20251022_143100_large_video_720p.mp4
        ├── 20251022_143105_image.webp
        └── ...
```

## Error Handling

```python
def safe_convert(file_path: str):
    """Convert with comprehensive error handling"""
    try:
        response = requests.post(
            f"{API_URL}/convert/mp3/file/",
            files={'file': open(file_path, 'rb')},
            data={'use_s3': True, 'return_base64': False},
            headers={'X-API-Key': API_KEY}
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Check for S3 upload errors
            if 's3_upload_error' in result:
                print(f"Warning: S3 upload failed - {result['s3_upload_error']}")
                # Fallback to base64 if needed
                return result.get('file_base64')
            
            return result['download_url']
            
        elif response.status_code == 401:
            print("Error: Invalid API key")
        elif response.status_code == 400:
            print(f"Error: Invalid request - {response.json()['detail']}")
        else:
            print(f"Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Exception: {str(e)}")
    
    return None
```

## Performance Considerations

### File Size Limits
- **MP3 conversion**: Handles files up to 2GB
- **Video compression**: Best for files under 1GB
- **WebP conversion**: Best for images under 50MB

### Processing Times (Approximate)
- **MP3 conversion**: ~1-2 minutes per 100MB
- **Video compression (720p)**: ~2-5 minutes per 100MB
- **WebP conversion**: ~1-5 seconds per 10MB

### S3 Upload Times
- Depends on file size and network speed
- Typical: 5-30 seconds for 50MB file

## Security Best Practices

1. **API Key Protection**
   - Store API keys in environment variables
   - Rotate keys regularly
   - Use different keys for development/production

2. **S3 Bucket Security**
   - Only allow public read for converted files folder
   - Use IAM roles with minimal permissions
   - Enable S3 logging and monitoring

3. **File Validation**
   - API validates file formats automatically
   - Implement size limits at application level
   - Scan uploaded files for malware

## Troubleshooting

### S3 Upload Fails

**Problem:** `s3_upload_error` in response

**Solutions:**
1. Check AWS credentials are correct
2. Verify bucket policy allows public-read
3. Ensure bucket exists and is accessible
4. Check IAM permissions for PutObject

### Download URL Not Accessible

**Problem:** 403 Forbidden on download URL

**Solutions:**
1. Verify bucket ACL settings
2. Check object ACL (should be public-read)
3. Disable "Block all public access" for the folder
4. Wait a few seconds for propagation

### Base64 Response Too Large

**Problem:** Response payload exceeds limits

**Solutions:**
1. Set `return_base64=False`
2. Use S3 URLs only for large files
3. Implement streaming for very large files

## API Health Check

```bash
curl http://localhost:8000/
```

**Response:**
```json
{
  "message": "PDF, Image OCR, and Media Converter API with S3 Storage",
  "version": "2.0.0",
  "features": [
    "PDF text extraction",
    "Image OCR",
    "PDF splitting",
    "MP4 to MP3 conversion",
    "Video compression",
    "Image to WebP conversion",
    "S3 storage integration"
  ],
  "s3_enabled": true,
  "endpoints": {
    "media": [
      "/convert/mp3/file/",
      "/convert/mp3/base64/",
      "/convert/compress-video/file/",
      "/convert/compress-video/base64/"
    ],
    "image": [
      "/convert/webp/file/",
      "/convert/webp/base64/"
    ]
  }
}
```

## License

MIT License - See LICENSE file for details

## Support

For issues or questions:
- GitHub Issues: [your-repo]/issues
- Email: support@example.com
- Documentation: [your-docs-url]
