# ocr_demo.py
import pytesseract
from PIL import Image
import cv2
import re
import sys

# Windows: Set this path exactly where your tesseract.exe is installed
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def preprocess_image(path):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Image not found: {path}")
    
    # Convert to gray
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Upscale for better OCR
    gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    
    # Remove noise
    gray = cv2.medianBlur(gray, 3)
    
    # Increase contrast
    th = cv2.adaptiveThreshold(gray, 255,
                               cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, 11, 2)
    return th

def ocr_from_image(path):
    processed = preprocess_image(path)
    pil_img = Image.fromarray(processed)
    text = pytesseract.image_to_string(pil_img, lang='eng')
    return text

def find_expiry(text):
    # Regex patterns to detect expiry formats like:
    # 12/2024 , DEC 2025 , April 2026 , 12-2024
    expiry_patterns = [
        r'(\d{1,2}[\/\-\.\s]\d{4})',
        r'([A-Za-z]{3,9}\s*\d{4})',
        r'(\d{2}\s*[A-Za-z]{3}\s*\d{4})',
        r'(\d{2}\-\d{2}\-\d{4})'
    ]
    
    for pattern in expiry_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None

if __name__ == "__main__":
    # If no argument, use test_medicine.jpg
    path = sys.argv[1] if len(sys.argv) > 1 else "test_medicine.jpg"
    
    try:
        text = ocr_from_image(path)
        print("------ OCR TEXT ------")
        print(text)

        expiry = find_expiry(text)
        print("------ EXPIRY DETECTED ------")
        print(expiry)

    except Exception as e:
        print("Error:", e)
