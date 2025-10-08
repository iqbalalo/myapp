# API Key Management & Usage Guide

## Setup

1. **Create .env file** in your project root with the master API key:
```bash
DEFAULT_API_KEY=Pass#0123456789#?
```

2. **Deploy with Docker Compose**:
```bash
docker-compose up -d --build
```

3. **Create api-keys.json** (optional - will be auto-created):
```bash
touch api-keys.json
```

---

## API Key Management

### 1. Create a New API Key

**Endpoint:** `POST /api/keys/create/`

**Headers:**
```
X-API-Key: Pass#0123456789#?
```

**Request Body:**
```json
{
  "email": "user@example.com",
  "expires": "30"
}
```

- `expires` can be:
  - `"never"` - No expiration
  - `"30"` - Expires in 30 days
  - `"90"` - Expires in 90 days
  - `"365"` - Expires in 1 year

**Response:**
```json
{
  "success": true,
  "api_key": "sk_xxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "email": "user@example.com",
  "created_at": "2025-10-09T12:00:00",
  "expires": "2025-11-08T12:00:00",
  "message": "API key created successfully. Store this key securely - it won't be shown again."
}
```

**cURL Example:**
```bash
curl -X POST "http://52.196.69.248:8080/api/api/keys/create/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "expires": "30"
  }'
```

---

### 2. List All API Keys

**Endpoint:** `GET /api/keys/list/`

**Headers:**
```
X-API-Key: Pass#0123456789#?
```

**Response:**
```json
{
  "success": true,
  "total_keys": 2,
  "api_keys": [
    {
      "api_key_masked": "sk_abcdefgh...xyz12345",
      "api_key_full": "sk_abcdefghijklmnopqrstuvwxyz12345",
      "email": "user1@example.com",
      "created_at": "2025-10-09T12:00:00",
      "expires": "2025-11-08T12:00:00",
      "status": "Active"
    },
    {
      "api_key_masked": "sk_12345678...abcd9999",
      "api_key_full": "sk_12345678901234567890abcd9999",
      "email": "user2@example.com",
      "created_at": "2025-10-01T10:00:00",
      "expires": "Never",
      "status": "Active"
    }
  ]
}
```

**cURL Example:**
```bash
curl -X GET "http://52.196.69.248:8080/api/api/keys/list/" \
  -H "X-API-Key: Pass#0123456789#?"
```

---

### 3. Delete an API Key

**Endpoint:** `DELETE /api/keys/delete/`

**Headers:**
```
X-API-Key: Pass#0123456789#?
```

**Request Body:**
```json
{
  "api_key": "sk_xxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

**Response:**
```json
{
  "success": true,
  "message": "API key deleted successfully",
  "deleted_key": {
    "email": "user@example.com",
    "created_at": "2025-10-09T12:00:00"
  }
}
```

**cURL Example:**
```bash
curl -X DELETE "http://52.196.69.248:8080/api/api/keys/delete/" \
  -H "X-API-Key: Pass#0123456789#?" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "sk_xxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }'
```

---

## OCR Extraction Endpoints (Requires API Key)

All extraction endpoints require a valid API key in the `X-API-Key` header.

### 1. Extract Text from File (PDF or Image)

**Endpoint:** `POST /extract/file/`

**Headers:**
```
X-API-Key: sk_your_api_key_here
```

**Form Data:**
- `file`: PDF or image file (JPEG, PNG, TIFF, BMP, GIF, WEBP)
- `use_ocr`: `true` or `false` (PDF only, default: `true`)
- `ocr_language`: Language code (default: `eng+jpn`)
  - Examples: `eng`, `jpn`, `ben`, `eng+jpn`, `eng+ben`, `eng+jpn+ben`

**Python Example:**
```python
import requests

# For Bengali text
files = {'file': open('bengali_image.jpg', 'rb')}
data = {
    'use_ocr': True,
    'ocr_language': 'ben'  # or 'eng+ben' for both
}
headers = {
    'X-API-Key': 'sk_your_api_key_here'
}

response = requests.post(
    'http://52.196.69.248:8080/api/extract/file/',
    files=files,
    data=data,
    headers=headers
)
print(response.json())
```

**cURL Example:**
```bash
curl -X POST "http://52.196.69.248:8080/api/extract/file/" \
  -H "X-API-Key: sk_your_api_key_here" \
  -F "file=@document.pdf" \
  -F "use_ocr=true" \
  -F "ocr_language=eng+jpn"
```

---

### 2. Extract Text from Base64 PDF

**Endpoint:** `POST /extract/base64/`

**Headers:**
```
X-API-Key: sk_your_api_key_here
Content-Type: application/json
```

**Request Body:**
```json
{
  "file_base64": "JVBERi0xLjQKJeLjz9...",
  "use_ocr": true,
  "ocr_language": "eng+jpn"
}
```

**Python Example:**
```python
import requests
import base64

with open('document.pdf', 'rb') as f:
    pdf_base64 = base64.b64encode(f.read()).decode('utf-8')

data = {
    'file_base64': pdf_base64,
    'use_ocr': True,
    'ocr_language': 'eng+jpn'
}
headers = {
    'X-API-Key': 'sk_your_api_key_here'
}

response = requests.post(
    'http://52.196.69.248:8080/api/extract/base64/',
    json=data,
    headers=headers
)
print(response.json())
```

---

### 3. Extract Text from Base64 Image

**Endpoint:** `POST /extract/image/base64/`

**Headers:**
```
X-API-Key: sk_your_api_key_here
Content-Type: application/json
```

**Request Body:**
```json
{
  "file_base64": "/9j/4AAQSkZJRgABAQEA...",
  "ocr_language": "ben"
}
```

**Python Example (Bengali Image):**
```python
import requests
import base64

with open('bengali_document.jpg', 'rb') as f:
    image_base64 = base64.b64encode(f.read()).decode('utf-8')

data = {
    'file_base64': image_base64,
    'ocr_language': 'ben'  # Bengali only
}
headers = {
    'X-API-Key': 'sk_your_api_key_here'
}

response = requests.post(
    'http://52.196.69.248:8080/api/extract/image/base64/',
    json=data,
    headers=headers
)
print(response.json())
```

**cURL Example:**
```bash
# First, encode image to base64
IMAGE_BASE64=$(base64 -w 0 image.jpg)

curl -X POST "http://52.196.69.248:8080/api/extract/image/base64/" \
  -H "X-API-Key: sk_your_api_key_here" \
  -H "Content-Type: application/json" \
  -d "{
    \"file_base64\": \"$IMAGE_BASE64\",
    \"ocr_language\": \"ben\"
  }"
```

---

### 4. Get Tesseract Languages

**Endpoint:** `GET /tesseract/languages/`

**Headers:**
```
X-API-Key: sk_your_api_key_here
```

**Response:**
```json
{
  "installed_languages": ["eng", "jpn", "ben", "osd"],
  "note": "Use '+' to combine languages, e.g., 'eng+ben' for English and Bengali"
}
```

**cURL Example:**
```bash
curl -X GET "http://52.196.69.248:8080/api/tesseract/languages/" \
  -H "X-API-Key: sk_your_api_key_here"
```

---

## Language Code Reference

| Language | Code | Example Usage |
|----------|------|---------------|
| English | `eng` | `ocr_language: "eng"` |
| Japanese | `jpn` | `ocr_language: "jpn"` |
| Bengali | `ben` | `ocr_language: "ben"` |
| English + Japanese | `eng+jpn` | `ocr_language: "eng+jpn"` |
| English + Bengali | `eng+ben` | `ocr_language: "eng+ben"` |
| All three | `eng+jpn+ben` | `ocr_language: "eng+jpn+ben"` |

---

## Response Format

### Success Response
```json
{
  "file_hash": "abc123...",
  "file_text": "Extracted text content...",
  "error": null,
  "metadata": {
    "total_pages": 5,
    "pdf_pages": 3,
    "ocr_pages": 2
  }
}
```

### Error Response
```json
{
  "detail": "Invalid or expired API key"
}
```

---

## Security Notes

1. **Master API Key**: `Pass#0123456789#?` (from .env)
   - Only used for admin operations (create/list/delete API keys)
   - Cannot be deleted
   - Store securely

2. **Generated API Keys**: Start with `sk_`
   - Used for OCR extraction endpoints
   - Can have expiration dates
   - Can be deleted by admin

3. **API Key Storage**: 
   - Keys are stored in `api-keys.json`
   - File is mounted in Docker container for persistence
   - Backup this file regularly

---

## Complete Python Client Example

```python
import requests
import base64
from typing import Optional

class OCRClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.headers = {'X-API-Key': api_key}
    
    def extract_from_file(
        self, 
        file_path: str, 
        use_ocr: bool = True, 
        ocr_language: str = "eng+jpn"
    ):
        """Extract text from PDF or image file."""
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {
                'use_ocr': use_ocr,
                'ocr_language': ocr_language
            }
            response = requests.post(
                f'{self.base_url}/extract/file/',
                files=files,
                data=data,
                headers=self.headers
            )
            return response.json()
    
    def extract_from_base64_image(
        self, 
        image_path: str, 
        ocr_language: str = "ben"
    ):
        """Extract text from base64 encoded image."""
        with open(image_path, 'rb') as f:
            image_base64 = base64.b64encode(f.read()).decode('utf-8')
        
        data = {
            'file_base64': image_base64,
            'ocr_language': ocr_language
        }
        response = requests.post(
            f'{self.base_url}/extract/image/base64/',
            json=data,
            headers=self.headers
        )
        return response.json()
    
    def get_languages(self):
        """Get list of installed Tesseract languages."""
        response = requests.get(
            f'{self.base_url}/tesseract/languages/',
            headers=self.headers
        )
        return response.json()


# Usage
if __name__ == "__main__":
    # Initialize client
    client = OCRClient(
        base_url="http://52.196.69.248:8080/api",
        api_key="sk_your_api_key_here"
    )
    
    # Extract from Bengali image
    result = client.extract_from_base64_image(
        'bengali_doc.jpg',
        ocr_language='ben'
    )
    print("Bengali Text:", result['file_text'])
    
    # Extract from English PDF
    result = client.extract_from_file(
        'document.pdf',
        use_ocr=True,
        ocr_language='eng'
    )
    print("English Text:", result['file_text'])
    
    # Get available languages
    languages = client.get_languages()
    print("Available languages:", languages['installed_languages'])
```

---

## Admin Client Example

```python
import requests

class AdminClient:
    def __init__(self, base_url: str, master_key: str):
        self.base_url = base_url.rstrip('/')
        self.headers = {'X-API-Key': master_key}
    
    def create_api_key(self, email: str, expires: str = "never"):
        """Create a new API key."""
        data = {
            'email': email,
            'expires': expires
        }
        response = requests.post(
            f'{self.base_url}/api/keys/create/',
            json=data,
            headers=self.headers
        )
        return response.json()
    
    def list_api_keys(self):
        """List all API keys."""
        response = requests.get(
            f'{self.base_url}/api/keys/list/',
            headers=self.headers
        )
        return response.json()
    
    def delete_api_key(self, api_key: str):
        """Delete an API key."""
        data = {'api_key': api_key}
        response = requests.delete(
            f'{self.base_url}/api/keys/delete/',
            json=data,
            headers=self.headers
        )
        return response.json()


# Usage
if __name__ == "__main__":
    admin = AdminClient(
        base_url="http://52.196.69.248:8080/api",
        master_key="Pass#0123456789#?"
    )
    
    # Create new API key
    new_key = admin.create_api_key(
        email="newuser@example.com",
        expires="90"  # 90 days
    )
    print("New API Key:", new_key['api_key'])
    
    # List all keys
    keys = admin.list_api_keys()
    print(f"Total API Keys: {keys['total_keys']}")
    for key in keys['api_keys']:
        print(f"  - {key['email']}: {key['api_key_masked']} ({key['status']})")
    
    # Delete a key
    # result = admin.delete_api_key("sk_old_key_to_delete")
    # print(result['message'])
```

---

## Troubleshooting

### Issue: "Invalid or expired API key"
**Solution:** 
- Verify the API key is correct
- Check if the key has expired using `/api/keys/list/`
- Create a new key if needed

### Issue: Bengali text not recognized
**Solution:**
- Ensure you're passing `ocr_language: "ben"` in the request
- Verify Bengali is installed: Check `/tesseract/languages/`
- Try combining with English: `ocr_language: "eng+ben"`

### Issue: "Master API key required for this operation"
**Solution:**
- Use the master key from `.env` file for admin operations
- Only admin endpoints require the master key
- Regular extraction endpoints can use any valid API key

### Issue: api-keys.json not persisting
**Solution:**
- Ensure the volume mount in docker-compose.yml is correct:
  ```yaml
  volumes:
    - ./api-keys.json:/app/api-keys.json
  ```
- Create an empty file first: `touch api-keys.json`
- Check file permissions

---

## File Structure

```
project/
├── .env                    # Environment variables (master API key)
├── .gitignore
├── docker-compose.yml      # Docker services configuration
├── Dockerfile.api          # API Docker image
├── nginx.conf             # Nginx reverse proxy config
├── api-keys.json          # API keys storage (auto-created)
└── api_files/
    ├── main.py            # FastAPI application
    ├── pdf_processor.py   # PDF extraction logic
    ├── image_processor.py # Image extraction logic
    └── requirements.txt   # Python dependencies
```

---

## Important Notes

1. **Always use HTTPS in production** - This guide uses HTTP for demonstration
2. **Backup api-keys.json regularly** - This file contains all API keys
3. **Rotate the master API key** - Change it in `.env` and redeploy
4. **Monitor API key usage** - Implement logging/analytics as needed
5. **Set appropriate expiration** - Short-lived keys for testing, longer for production