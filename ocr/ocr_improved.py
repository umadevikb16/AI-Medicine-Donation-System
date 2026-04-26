# ocr_improved.py
import cv2
import pytesseract
from PIL import Image
import numpy as np
import sys
import re

# Windows: set this to your tesseract.exe location
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def clahe(img_gray):
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    return clahe.apply(img_gray)

def sharpen(img):
    kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]])
    return cv2.filter2D(img, -1, kernel)

def preprocess_for_text(img, upscale=1.6):
    # img: grayscale
    h, w = img.shape[:2]
    if upscale != 1.0:
        img = cv2.resize(img, (int(w*upscale), int(h*upscale)), interpolation=cv2.INTER_CUBIC)
    img = clahe(img)
    img = cv2.medianBlur(img, 3)
    img = sharpen(img)
    # Otsu threshold
    _, th = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th

def run_tesseract_on_pil(pil_img, config="--psm 6 --oem 3"):
    text = pytesseract.image_to_string(pil_img, lang='eng', config=config)
    data = pytesseract.image_to_data(pil_img, lang='eng', config=config, output_type=pytesseract.Output.DICT)
    # collect high confidence words
    conf_words = []
    for i, w in enumerate(data.get('text', [])):
        try:
            conf = int(float(data.get('conf', [])[i]))
        except:
            conf = -1
        if w.strip() and conf > 40:
            conf_words.append((w.strip(), conf))
    return text.strip(), conf_words, data

def crop_and_process(img_path):
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        raise FileNotFoundError(img_path)
    h, w = img_bgr.shape[:2]

    results = {}

    # 1) Right vertical strip (expiry/manufacture + blue vertical text)
    # Crop the right 30% (adjustable)
    right_x = int(w * 0.70)
    crop_r = img_bgr[0:h, right_x:w]
    # rotate 90 degrees CCW to make vertical text horizontal
    crop_r_rot = cv2.rotate(crop_r, cv2.ROTATE_90_COUNTERCLOCKWISE)
    gray_r = cv2.cvtColor(crop_r_rot, cv2.COLOR_BGR2GRAY)
    pre_r = preprocess_for_text(gray_r, upscale=1.3)
    pil_r = Image.fromarray(pre_r)
    # Tesseract config for digits & uppercase month names (allow letters and digits and '/.')
    cfg_r = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/.-"
    text_r, conf_r, data_r = run_tesseract_on_pil(pil_r, config=cfg_r)
    results['right_strip'] = {'text': text_r, 'confident_words': conf_r}

    # 2) Middle / brand area where large product name appears
    # Crop center-bottom (adjust as your blister layout)
    top = int(h * 0.35)
    bottom = int(h * 0.75)
    left = int(w * 0.05)
    right = int(w * 0.95)
    crop_m = img_bgr[top:bottom, left:right]
    gray_m = cv2.cvtColor(crop_m, cv2.COLOR_BGR2GRAY)
    pre_m = preprocess_for_text(gray_m, upscale=1.6)
    pil_m = Image.fromarray(pre_m)
    cfg_m = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
    text_m, conf_m, data_m = run_tesseract_on_pil(pil_m, config=cfg_m)
    results['brand_area'] = {'text': text_m, 'confident_words': conf_m}

    # 3) Full image OCR (fallback) - lower confidence threshold
    gray_full = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    pre_full = preprocess_for_text(gray_full, upscale=1.2)
    pil_full = Image.fromarray(pre_full)
    cfg_full = "--psm 3 --oem 3"
    text_f, conf_f, data_f = run_tesseract_on_pil(pil_full, config=cfg_full)
    results['full_image'] = {'text': text_f, 'confident_words': conf_f}

    return results

def find_expiry_from_text(s):
    if not s: 
        return None
    s = s.replace('\n', ' ').replace(':',' ').strip()
    # Common patterns
    patterns = [
        r'EXP(?:\s|IRY)?\s*(\d{1,2}[\/\-\.\s]\d{2,4})',   # EXP 07/2026 or EXP JUL 2026
        r'(\d{1,2}[\/\-\.\s]\d{4})',                     # 07/2026
        r'([A-Z]{3,9}\s*\d{4})',                        # JUL 2026
        r'([A-Z]{3,9}\s*\d{2})'                         # JUL 26
    ]
    s_up = s.upper()
    for p in patterns:
        m = re.search(p, s_up, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # normalize mm/yy to mm/yyyy
            m2 = re.match(r'(\d{1,2})[\/\-\.\s](\d{2})$', raw)
            if m2:
                mm = int(m2.group(1)); yy = int(m2.group(2))
                yyyy = 2000 + yy if yy < 80 else 1900 + yy
                return f"{mm:02d}/{yyyy}"
            m3 = re.match(r'(\d{1,2})[\/\-\.\s](\d{4})$', raw)
            if m3:
                return f"{int(m3.group(1)):02d}/{m3.group(2)}"
            # month + year
            m4 = re.match(r'([A-Z]{3,9})\s*(\d{2,4})', raw, flags=re.IGNORECASE)
            if m4:
                mon = m4.group(1).title()
                yr = m4.group(2)
                if len(yr)==2: yr = str(2000 + int(yr))
                return f"{mon} {yr}"
            return raw
    return None

if __name__ == "__main__":
    img = sys.argv[1] if len(sys.argv)>1 else "test_medicine.jpg"
    res = crop_and_process(img)

    print("\n--- RIGHT STRIP (Expiry block) ---")
    print(res['right_strip']['text'])
    print("Confident words:", res['right_strip']['confident_words'])
    expiry_guess = find_expiry_from_text(res['right_strip']['text'])
    print("Expiry (parsed):", expiry_guess)

    print("\n--- BRAND AREA (Product name / ingredient) ---")
    print(res['brand_area']['text'][:800])
    print("Confident words:", res['brand_area']['confident_words'])

    print("\n--- FULL IMAGE (fallback) ---")
    print(res['full_image']['text'][:800])
    print("Confident words:", res['full_image']['confident_words'])
