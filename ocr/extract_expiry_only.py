import pytesseract
import cv2
from PIL import Image
import re

# Path to your tesseract installation
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def find_expiry(s):
    if not s:
        return None
    s = s.upper().replace("\n", " ")
    
    patterns = [
        r'EXP[:\s]*([A-Z]{3,9}\s*\d{4})',       # EXP JUL 2026
        r'EXP[:\s]*(\d{1,2}[\/\-\.\s]\d{2,4})', # EXP 07/2026
        r'([A-Z]{3,9}\s*\d{4})',                # JUL 2026
        r'(\d{1,2}[\/\-\.\s]\d{4})',            # 07/2026
        r'(\d{1,2}[\/\-\.\s]\d{2})'             # 07/26
    ]
    
    for p in patterns:
        m = re.search(p, s)
        if m:
            return m.group(1).strip()
    return None

# ---------- MAIN ----------
img_path = r"ocr_crops/crop_right_w85_rotCW.png"

img = cv2.imread(img_path)
if img is None:
    print("Image not found:", img_path)
    exit()

# Convert to PIL
pil_img = Image.fromarray(img)

# OCR with strict whitelist
config = "--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:/.-"
text = pytesseract.image_to_string(pil_img, config=config)

print("\n--- RAW OCR TEXT ---")
print(text)

expiry = find_expiry(text)
print("\n--- PARSED EXPIRY ---")
print(expiry)
